"""以路径和交易日块为单位生成一致的合成行情。"""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pandas as pd

from options_strategies.simulation.chain import CONTRACT_COLUMNS
from options_strategies.simulation.chain import ContractBook
from options_strategies.simulation.config import SimulationConfig
from options_strategies.simulation.paths import STOCK_COLUMNS
from options_strategies.simulation.paths import market_state
from options_strategies.simulation.paths import stock_path
from options_strategies.simulation.pricing import AmericanPricer
from options_strategies.simulation.pricing import make_quote


OPTION_COLUMNS = [
    "contract_id",
    "underlying_symbol",
    "option_type",
    "expiration",
    "strike",
    "expiration_type",
    "multiplier",
    "quote_date",
    "underlying_price",
    "implied_volatility",
    "theoretical_price",
    "delta",
    "gamma",
    "bid",
    "ask",
    "pricing_refinement",
    "greeks_method",
]
SETTLEMENT_COLUMNS = [
    "contract_id",
    "underlying_symbol",
    "quote_date",
    "expiration",
    "option_type",
    "strike",
    "underlying_price",
    "settlement_price",
    "multiplier",
]
STATE_COLUMNS = ["realized_volatility", "implied_volatility", "spread_multiplier", "price_factor"]
TABLE_COLUMNS = {
    "stock": ["path_id", *STOCK_COLUMNS, *STATE_COLUMNS],
    "options": ["path_id", *OPTION_COLUMNS],
    "contracts": ["path_id", *CONTRACT_COLUMNS],
    "settlements": ["path_id", *SETTLEMENT_COLUMNS],
}
STRING_COLUMNS = {"contract_id", "underlying_symbol", "option_type", "expiration_type", "greeks_method"}
DATE_COLUMNS = {"quote_date", "expiration", "listed_date"}
INT_COLUMNS = {"path_id", "volume", "multiplier", "pricing_refinement"}


def table_frame(name: str, rows) -> pd.DataFrame:
    """包括空表在内始终输出稳定的列顺序和 dtype。"""
    frame = pd.DataFrame(rows, columns=TABLE_COLUMNS[name])
    for column in frame:
        if column in DATE_COLUMNS:
            frame[column] = pd.to_datetime(frame[column]).astype("datetime64[ns]")
        elif column in STRING_COLUMNS:
            frame[column] = frame[column].astype(object)
        else:
            frame[column] = frame[column].astype("int64" if column in INT_COLUMNS else "float64")
    return frame


@dataclass
class MarketBatch:
    """一个路径中连续交易日块的四张数据表。"""

    path_id: int
    batch_id: int
    tables: dict[str, pd.DataFrame]


@dataclass
class MarketPath:
    """可直接在 Notebook 中使用的一条完整市场路径。"""

    path_id: int
    stock: pd.DataFrame
    options: pd.DataFrame
    contracts: pd.DataFrame
    settlements: pd.DataFrame
    metadata: dict = field(default_factory=dict)

    def for_symbol(self, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """复制为 optopsy 的 options_df、stock_df；结算表不作为成交报价。"""
        if symbol not in set(self.stock.underlying_symbol):
            raise KeyError(f"路径没有标的: {symbol}")
        options = self.options[self.options.underlying_symbol == symbol].drop(columns=["path_id", "contract_id"])
        stock = self.stock[self.stock.underlying_symbol == symbol].drop(columns=["path_id"])
        return options.copy().reset_index(drop=True), stock.copy().reset_index(drop=True)


class MonteCarloSource:
    """串行数据源；各路径之间、各情景之间均不共享随机流状态。"""

    def __init__(self, config: SimulationConfig):
        """使用已验证的不可变配置创建数据源。"""
        self.config = config
        self._pricer = AmericanPricer(config.pricing)

    def iter_batches(self, path_id: int):
        """生成交易日块，内存中仅保留日线、存续合约簿及当前块报价。"""
        stock = stock_path(self.config, path_id)
        symbols = {item.symbol: item for item in self.config.symbols}
        book = ContractBook(self.config.chain)
        rows = {name: [] for name in TABLE_COLUMNS}
        days = list(stock.groupby("quote_date", sort=True))
        with self._pricer as pricer:
            for day_index, (timestamp, day_stock) in enumerate(days):
                day = timestamp.date()
                state = market_state(self.config, day)
                spots = dict(zip(day_stock.underlying_symbol, day_stock.close, strict=True))
                for row in day_stock.to_dict("records"):
                    rows["stock"].append({"path_id": path_id, **row, **state[row["underlying_symbol"]]})
                for symbol, item in symbols.items():
                    new = book.list_contracts(day, item, spots[symbol])
                    rows["contracts"].extend({"path_id": path_id, **contract} for contract in new)
                for contract in book.active.values():
                    symbol = contract["underlying_symbol"]
                    spot = spots[symbol]
                    common = {"path_id": path_id, **contract, "quote_date": day, "underlying_price": spot}
                    if contract["expiration"] == day:
                        difference = spot - contract["strike"]
                        intrinsic = max(0.0, difference if contract["option_type"] == "c" else -difference)
                        rows["settlements"].append({**common, "settlement_price": intrinsic})
                    else:
                        iv = state[symbol]["implied_volatility"]
                        try:
                            values = pricer.price(
                                day, contract["expiration"], spot, contract["strike"], iv, contract["option_type"]
                            )
                            quote = make_quote(
                                values["theoretical_price"], self.config.quotes, state[symbol]["spread_multiplier"]
                            )
                        except Exception as error:
                            raise RuntimeError(
                                f"定价失败: path={path_id}, date={day}, contract={contract['contract_id']}: {error}"
                            ) from error
                        rows["options"].append({**common, "implied_volatility": iv, **values, **quote})
                book.retire(day)
                if (day_index + 1) % self.config.chunk_sessions == 0 or day_index == len(days) - 1:
                    batch = MarketBatch(
                        path_id,
                        day_index // self.config.chunk_sessions,
                        {name: table_frame(name, values) for name, values in rows.items()},
                    )
                    rows = {name: [] for name in TABLE_COLUMNS}
                    yield batch

    def generate_path(self, path_id: int = 0) -> MarketPath:
        """将一条路径完整装入内存，适用于小数据交互分析。"""
        tables = {name: [] for name in TABLE_COLUMNS}
        for batch in self.iter_batches(path_id):
            for name, frame in batch.tables.items():
                tables[name].append(frame)
        return MarketPath(
            path_id,
            **{name: pd.concat(parts, ignore_index=True) for name, parts in tables.items()},
            metadata={"config": self.config.model_dump(mode="json"), "path_id": path_id},
        )

    def generate_to(self, output_dir: str | Path, path_ids=None, *, resume: bool = False):
        """分片持久化；在函数内导入以避免存储层循环依赖。"""
        from options_strategies.simulation.storage import generate_to  # noqa: PLC0415

        return generate_to(self, output_dir, path_ids=path_ids, resume=resume)
