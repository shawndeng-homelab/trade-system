"""带校验和、单写入锁及路径级恢复的 Parquet 数据集。"""

import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from options_strategies.simulation.calendar import sessions
from options_strategies.simulation.config import SimulationConfig
from options_strategies.simulation.paths import market_state
from options_strategies.simulation.source import STRING_COLUMNS
from options_strategies.simulation.source import TABLE_COLUMNS
from options_strategies.simulation.source import MarketPath
from options_strategies.simulation.source import table_frame
from options_strategies.simulation.validation import validate_frame


def checksum(path: Path) -> str:
    """以固定缓冲区计算文件摘要。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance() -> dict:
    """记录会改变生成结果的软件及实现版本。"""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return {
        "generator_schema": 1,
        "source_sha256": digest.hexdigest(),
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("QuantLib", "numpy", "pandas", "pyarrow", "pydantic", "optopsy")
        },
        "rng": "PCG64/SeedSequence([seed,path_id,0])",
        "calendar": "QuantLib/UnitedStates.NYSE",
        "day_count": "Actual365Fixed",
        "ohlc_substeps": 16,
        "volume": "zero_placeholder",
        "cash_dividends": [],
        "limitations": [
            "合成挂牌，非真实挂牌历史",
            "日频数据不验证真实日内 0DTE",
            "未模拟指派、交割和股息现金流",
            "固定横截面 IV，无偏斜和期限结构",
        ],
    }


def write_manifest(root: Path, manifest: dict) -> None:
    """完整写入临时文件后原子替换清单。"""
    handle, name = tempfile.mkstemp(prefix=".manifest-", dir=root)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / "manifest.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def writer_lock(root: Path):
    """操作系统释放崩溃进程的锁，避免残留标记阻碍恢复。"""
    with (root / ".writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("数据集已有写入进程") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class SimulationDataset:
    """离线读取和验证一个版本化数据集。"""

    def __init__(self, root: Path, manifest: dict):
        """通过 open 加载并验证配置。"""
        self.root = root
        self.manifest = manifest
        self.config = SimulationConfig.model_validate(manifest["config"])

    @classmethod
    def open(cls, path: str | Path):
        """读取清单，不要求所有路径已完成。"""
        root = Path(path).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("不支持的数据集清单版本")
        dataset = cls(root, manifest)
        if dataset.config.fingerprint() != manifest.get("config_sha256"):
            raise ValueError("配置摘要不匹配")
        for path_id in manifest["paths"]:
            if not path_id.isdecimal() or str(int(path_id)) != path_id or not 0 <= int(path_id) < 2**32:
                raise ValueError("清单中的路径编号无效")
        return dataset

    def _files(self, path_id: int, table: str):
        entry = self.manifest["paths"][str(path_id)]
        for record in entry["files"]:
            if record["table"] not in TABLE_COLUMNS:
                raise ValueError("未知数据表")
            if record["table"] != table:
                continue
            if not re.fullmatch(rf"{table}-[0-9]{{6}}\.parquet", record["name"]):
                raise ValueError("无效分片文件名")
            path = self.root / f"path-{path_id:08d}" / record["name"]
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("分片文件不能指向数据集外部")
            if not path.is_file() or checksum(path) != record["sha256"]:
                raise ValueError(f"文件缺失或校验失败: {path}")
            yield path, record

    def iter_table(self, path_id: int, table: str):
        """校验后逐片读取，避免整体载入期权链。"""
        if table not in TABLE_COLUMNS:
            raise ValueError(f"未知数据表: {table}")
        for path, record in self._files(path_id, table):
            frame = pd.read_parquet(path)
            # pandas 3 默认将 Parquet 字符串读成 StringDtype；公开接口固定为 object。
            for column in STRING_COLUMNS & set(frame.columns):
                frame[column] = frame[column].astype(object)
            validate_frame(table, frame, path_id, self.config.quotes.tick_size)
            if len(frame) != record["rows"]:
                raise ValueError("分片行数与清单不匹配")
            yield frame

    def _read(self, path_id: int, name: str):
        parts = list(self.iter_table(path_id, name))
        return pd.concat(parts, ignore_index=True) if parts else table_frame(name, [])

    def validate_path(self, path_id: int, *, require_complete: bool = True) -> dict:
        """验证完整覆盖、合约身份、现价引用及结算关系。"""
        entry = self.manifest["paths"][str(path_id)]
        if require_complete and entry["status"] != "complete":
            raise ValueError(f"路径未完成: {path_id}/{entry['status']}")
        for table in TABLE_COLUMNS:
            records = [r for r in entry["files"] if r["table"] == table]
            expected_chunks = (
                len(sessions(self.config.start_date, self.config.end_date)) + self.config.chunk_sessions - 1
            ) // self.config.chunk_sessions
            if [r["name"] for r in records] != [f"{table}-{i:06d}.parquet" for i in range(expected_chunks)]:
                raise ValueError(f"分片列表缺失、乱序或重复: {table}")
        stock = self._read(path_id, "stock")
        names = [item.symbol for item in self.config.symbols]
        days = pd.to_datetime(sessions(self.config.start_date, self.config.end_date))
        expected = {(pd.Timestamp(day), symbol) for day in days for symbol in names}
        if len(stock) != len(expected) or set(zip(stock.quote_date, stock.underlying_symbol, strict=True)) != expected:
            raise ValueError("日线交易日/标的覆盖不完整或重复")
        spots = stock.set_index(["quote_date", "underlying_symbol"]).close
        stock_indexed = stock.set_index(["quote_date", "underlying_symbol"])
        for timestamp, day_stock in stock.groupby("quote_date"):
            state = market_state(self.config, timestamp.date())
            for row in day_stock.to_dict("records"):
                for name, value in state[row["underlying_symbol"]].items():
                    if row[name] != value:
                        raise ValueError(f"市场状态与情景配置不一致: {timestamp}/{name}")
        for item in self.config.symbols:
            symbol_stock = stock[stock.underlying_symbol == item.symbol].sort_values("quote_date")
            if not symbol_stock.iloc[0][["open", "high", "low", "close"]].eq(item.initial_price).all():
                raise ValueError("首日价格锚点错误")
            opening = symbol_stock.close.shift(1).iloc[1:] * symbol_stock.price_factor.iloc[1:]
            if not np_allclose(symbol_stock.open.iloc[1:].to_numpy(), opening.to_numpy()):
                raise ValueError("开盘冲击与配置不一致")
        contracts = self._read(path_id, "contracts")
        validate_frame("contracts", contracts, path_id, self.config.quotes.tick_size)
        catalog = contracts.set_index("contract_id")
        if not set(contracts.underlying_symbol) <= set(names):
            raise ValueError("合约包含未配置标的")
        if not set(contracts.listed_date) <= set(days):
            raise ValueError("合约上市日期不在模拟交易日内")
        counts = {"stock": len(stock), "contracts": len(contracts), "options": 0, "settlements": 0}
        observed = {"options": set(), "settlements": set()}
        for table in ("options", "settlements"):
            for frame in self.iter_table(path_id, table):
                counts[table] += len(frame)
                if frame.empty:
                    continue
                identity = catalog.reindex(frame.contract_id)
                for column in ("underlying_symbol", "option_type", "expiration", "strike", "multiplier"):
                    if not (identity[column].to_numpy() == frame[column].to_numpy()).all():
                        raise ValueError(f"合约身份不匹配: {column}")
                if (
                    "expiration_type" in frame
                    and not (identity.expiration_type.to_numpy() == frame.expiration_type.to_numpy()).all()
                ):
                    raise ValueError("到期类型发生变化")
                if (frame.quote_date.to_numpy() < identity.listed_date.to_numpy()).any():
                    raise ValueError("合约上市前出现报价")
                keys = pd.MultiIndex.from_arrays([frame.quote_date, frame.underlying_symbol])
                if not np_allclose(frame.underlying_price.to_numpy(), spots.reindex(keys).to_numpy()):
                    raise ValueError("期权现价与日线收盘价不一致")
                if table == "options":
                    if not np_allclose(
                        frame.implied_volatility.to_numpy(), stock_indexed.implied_volatility.reindex(keys).to_numpy()
                    ):
                        raise ValueError("期权 IV 与配置不一致")
                    if not frame.pricing_refinement.between(0, self.config.pricing.max_refinements).all():
                        raise ValueError("无效网格加密级别")
                for day, quotes in frame.groupby("quote_date", sort=False):
                    if day in observed[table]:
                        raise ValueError("同一交易日被重复分片")
                    observed[table].add(day)
                    mask = (
                        (catalog.listed_date <= day) & (catalog.expiration > day)
                        if table == "options"
                        else catalog.expiration.eq(day)
                    )
                    if set(quotes.contract_id) != set(catalog.index[mask]):
                        raise ValueError(f"存续合约报价/结算不完整: {table}/{day}")
        if observed["options"] != set(days):
            raise ValueError("缺少交易日期权报价")
        settlement_days = set(catalog.loc[catalog.expiration.between(days.min(), days.max()), "expiration"])
        if observed["settlements"] != settlement_days:
            raise ValueError("缺少到期结算")
        return counts

    def validate(self) -> dict:
        """完整验证全部已声明路径，未完成路径会报错。"""
        if not self.manifest["paths"]:
            raise ValueError("数据集不包含路径")
        return {key: self.validate_path(int(key)) for key in self.manifest["paths"]}

    def load_path(self, path_id: int = 0) -> MarketPath:
        """完整验证后加载一条路径。"""
        self.validate_path(path_id)
        return MarketPath(
            path_id,
            **{name: self._read(path_id, name) for name in TABLE_COLUMNS},
            metadata={"config": self.manifest["config"], "provenance": self.manifest["provenance"], "path_id": path_id},
        )


def np_allclose(left, right) -> bool:
    """不允许缺失参考价格，使用固定数值容差。"""
    return bool(pd.Series(left).sub(right).abs().le(1e-10).all())


def generate_to(source, output_dir: str | Path, path_ids=None, *, resume: bool = False) -> SimulationDataset:
    """串行生成并按路径提交；恢复时重建未完成路径。"""
    root = Path(output_dir).resolve()
    existed = root.exists()
    if existed and not resume:
        raise FileExistsError(f"数据集已存在: {root}")
    if existed and resume and not (root / "manifest.json").is_file():
        raise ValueError("不能恢复缺少清单的目录")
    ids = range(source.config.n_paths) if path_ids is None else path_ids
    root.mkdir(parents=True, exist_ok=True)
    with writer_lock(root):
        if (root / "manifest.json").exists():
            if not resume:
                raise FileExistsError(f"数据集已存在: {root}")
            dataset = SimulationDataset.open(root)
            if (
                dataset.config.fingerprint() != source.config.fingerprint()
                or dataset.manifest["provenance"] != provenance()
            ):
                raise ValueError("配置或生成器版本不同，不能恢复此数据集")
            manifest = dataset.manifest
        else:
            manifest = {
                "schema_version": 1,
                "config": source.config.model_dump(mode="json"),
                "config_sha256": source.config.fingerprint(),
                "provenance": provenance(),
                "paths": {},
            }
            write_manifest(root, manifest)
            dataset = SimulationDataset(root, manifest)
        requested = set()
        for path_id in ids:
            if isinstance(path_id, bool) or not isinstance(path_id, int) or not 0 <= path_id < 2**32:
                raise ValueError("path_id 必须是 [0, 2**32) 内的整数")
            if path_id in requested:
                raise ValueError("请求的路径编号重复")
            requested.add(path_id)
            key = str(path_id)
            if manifest["paths"].get(key, {}).get("status") == "complete":
                dataset.validate_path(path_id)
                continue
            target = root / f"path-{path_id:08d}"
            if target.is_symlink():
                raise ValueError("路径目录不能是符号链接")
            if target.exists() and key not in manifest["paths"]:
                raise FileExistsError(f"路径目录未登记，拒绝覆盖: {target}")
            if target.exists():
                shutil.rmtree(target)
            target.mkdir()
            entry = {"status": "generating", "files": []}
            manifest["paths"][key] = entry
            write_manifest(root, manifest)
            started = time.perf_counter()
            cache_hits = source._pricer.cache_hits
            solver_calls = source._pricer.solver_calls
            try:
                for batch in source.iter_batches(path_id):
                    for table, frame in batch.tables.items():
                        validate_frame(table, frame, path_id, source.config.quotes.tick_size)
                        name = f"{table}-{batch.batch_id:06d}.parquet"
                        temporary = target / f".{name}.tmp"
                        frame.to_parquet(temporary, index=False)
                        temporary.rename(target / name)
                        entry["files"].append(
                            {"table": table, "name": name, "rows": len(frame), "sha256": checksum(target / name)}
                        )
                    write_manifest(root, manifest)
                entry["rows"] = dataset.validate_path(path_id, require_complete=False)
                entry["elapsed_seconds"] = time.perf_counter() - started
                entry["pricing_cache_hits"] = source._pricer.cache_hits - cache_hits
                entry["pricing_solver_calls"] = source._pricer.solver_calls - solver_calls
                entry["status"] = "complete"
                write_manifest(root, manifest)
            except BaseException as error:
                entry["status"] = "failed"
                entry["error"] = f"{type(error).__name__}: {error}"
                write_manifest(root, manifest)
                raise
        if not requested:
            raise ValueError("至少请求一条路径")
    return dataset
