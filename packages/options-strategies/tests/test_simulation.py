"""验证合成市场的金融边界、复现性、存储恢复和真实策略接入。"""

import json
import math
import runpy
from datetime import date
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import QuantLib as ql
from click.testing import CliRunner
from options_strategies.benchmark import BenchmarkConfig
from options_strategies.benchmark import run_benchmark
from options_strategies.pmcc import PmccConfig
from options_strategies.pmcc import run_pmcc
from options_strategies.simulation import MonteCarloSource
from options_strategies.simulation import PricingConfig
from options_strategies.simulation import QuoteConfig
from options_strategies.simulation import SimulationConfig
from options_strategies.simulation import SimulationDataset
from options_strategies.simulation.calendar import qdate
from options_strategies.simulation.calendar import sessions
from options_strategies.simulation.chain import ContractBook
from options_strategies.simulation.chain import expirations
from options_strategies.simulation.cli import main
from options_strategies.simulation.paths import market_state
from options_strategies.simulation.paths import stock_path
from options_strategies.simulation.pricing import AmericanPricer
from options_strategies.simulation.pricing import make_quote
from options_strategies.simulation.source import TABLE_COLUMNS
from options_strategies.simulation.storage import checksum
from options_strategies.simulation.storage import write_manifest
from options_strategies.simulation.storage import writer_lock
from pandas.testing import assert_frame_equal
from pydantic import ValidationError


def config(**changes):
    """快速但使用真实有限差分定价的小合约链。"""
    values = {
        "start_date": "2024-01-02",
        "end_date": "2024-01-05",
        "symbols": [
            {
                "symbol": "SPY",
                "initial_price": 100,
                "mu": 0.03,
                "realized_volatility": 0.2,
                "implied_volatility": 0.25,
                "strike_step": 10,
            }
        ],
        "correlation": [[1]],
        "pricing": {"risk_free_rate": 0.04, "time_grid": 100, "price_grid": 200},
        "chain": {"weekly_expirations": 1, "monthly_expirations": 1, "strike_lower": 0.8, "strike_upper": 1.2},
        "chunk_sessions": 2,
    }
    values.update(changes)
    return SimulationConfig.model_validate(values)


@pytest.mark.parametrize(
    "change",
    [
        {
            "symbols": [
                {"symbol": "SPY", "initial_price": 0, "mu": 0, "realized_volatility": 0.2, "implied_volatility": 0.2}
            ]
        },
        {"correlation": [[0.5]]},
        {"correlation": [[float("nan")]]},
        {"correlation": [[1, 0], [0, 1]]},
        {"seed": -1},
        {"end_date": "2024-01-01"},
        {"start_date": "2024-01-06", "end_date": "2024-01-07"},
        {"cash_dividends": [{"date": "2024-01-03", "amount": 1}]},
        {"unexpected": 1},
        {"pricing": {"risk_free_rate": float("inf")}},
        {"events": [{"kind": "price_shock", "date": "2024-01-02", "symbols": ["SPY"], "factor": 0.8}]},
        {"events": [{"kind": "price_shock", "date": "2024-01-06", "symbols": ["SPY"], "factor": 0.8}]},
        {"events": [{"kind": "price_shock", "date": "2024-01-03", "symbols": ["QQQ"], "factor": 0.8}]},
        {
            "events": [
                {"kind": "parameter_override", "start_date": "2024-01-03", "end_date": "2024-01-04", "symbols": ["SPY"]}
            ]
        },
    ],
)
def test_invalid_configuration(change):
    """非法市场假设在昂贵计算之前失败。"""
    with pytest.raises(ValidationError):
        config(**change)


def test_event_overlap_and_matrix_validation():
    """拒绝冲突覆盖和非半正定矩阵，允许不同参数同时覆盖。"""
    event = {
        "kind": "parameter_override",
        "start_date": "2024-01-03",
        "end_date": "2024-01-04",
        "symbols": ["SPY"],
        "implied_volatility": 0.5,
    }
    with pytest.raises(ValidationError, match="冲突"):
        config(events=[event, event])
    config(events=[event, {**event, "implied_volatility": None, "spread_multiplier": 2}])
    symbols = [dict(config().symbols[0].model_dump(), symbol=s) for s in ("SPY", "QQQ", "IWM")]
    for matrix in ([[1, 0.2, 0.3], [0.1, 1, 0.2], [0.3, 0.2, 1]], [[1, -0.9, -0.9], [-0.9, 1, -0.9], [-0.9, -0.9, 1]]):
        with pytest.raises(ValidationError):
            config(symbols=symbols, correlation=matrix)


def test_calendar_and_expiration_rules():
    """处理休市、跨年及月度/周度重合。"""
    assert sessions(date(2024, 3, 28), date(2024, 4, 1)) == [date(2024, 3, 28), date(2024, 4, 1)]
    chain = config(chain={"weekly_expirations": 3, "monthly_expirations": 2}).chain
    dates = expirations(date(2024, 3, 25), chain)
    assert date(2024, 3, 28) in dates  # Good Friday 向前调整
    assert dates[date(2024, 4, 19)] == "monthly"
    assert all(day > date(2024, 12, 30) for day in expirations(date(2024, 12, 30), chain))


def test_gbm_statistics_and_correlation():
    """从独立路径收集标准化创新，验证分布及相关性。"""
    symbols = [dict(config().symbols[0].model_dump(), symbol=s) for s in ("SPY", "QQQ")]
    cfg = config(end_date="2024-02-16", symbols=symbols, correlation=[[1, 0.7], [0.7, 1]])
    innovations = []
    for path_id in range(160):
        prices = stock_path(cfg, path_id).pivot(index="quote_date", columns="underlying_symbol", values="close")
        # 显式恢复配置顺序，避免 pivot 的字母排序改变相关矩阵顺序。
        prices = prices[["SPY", "QQQ"]]
        dt = prices.index.to_series().diff().dt.days.iloc[1:].to_numpy() / 365
        increments = np.diff(np.log(prices.to_numpy()), axis=0)
        innovations.append((increments - (0.03 - 0.2**2 / 2) * dt[:, None]) / (0.2 * np.sqrt(dt[:, None])))
    samples = np.concatenate(innovations)
    n = len(samples)
    assert np.abs(samples.mean(axis=0)).max() < 5 / np.sqrt(n)
    assert np.abs(samples.var(axis=0) - 1).max() < 5 * np.sqrt(2 / n)
    assert abs(np.corrcoef(samples.T)[0, 1] - 0.7) < 0.04


def test_singular_correlation_and_rng_isolation():
    """完全相关路径可用，且不污染调用方的 NumPy 随机状态。"""
    symbols = [dict(config().symbols[0].model_dump(), symbol=s) for s in ("SPY", "QQQ")]
    cfg = config(symbols=symbols, correlation=[[1, 1], [1, 1]])
    np.random.seed(123)
    state = np.random.get_state()
    stock = stock_path(cfg, 2)
    after = np.random.get_state()
    assert np.array_equal(state[1], after[1]) and state[2:] == after[2:]
    assert np.array_equal(stock[stock.underlying_symbol == "SPY"].close, stock[stock.underlying_symbol == "QQQ"].close)
    assert_frame_equal(stock, stock_path(cfg, 2))
    assert not stock.close.equals(stock_path(cfg, 3).close)


def test_shock_path_and_parameter_restoration():
    """同种子下价格冲击只改变价格比例；IV 和价差覆盖不改变标的随机流。"""
    base = config()
    events = [
        {"kind": "price_shock", "date": "2024-01-03", "symbols": ["SPY"], "factor": 0.6},
        {
            "kind": "parameter_override",
            "start_date": "2024-01-03",
            "end_date": "2024-01-04",
            "symbols": ["SPY"],
            "implied_volatility": 0.5,
            "spread_multiplier": 3,
        },
    ]
    shocked = config(events=events)
    original, changed = stock_path(base, 0), stock_path(shocked, 0)
    assert changed.close.iloc[0] == original.close.iloc[0]
    assert np.allclose(changed.close.iloc[1:] / original.close.iloc[1:], 0.6)
    assert changed.open.iloc[1] == original.close.iloc[0] * 0.6
    assert market_state(shocked, date(2024, 1, 5))["SPY"]["implied_volatility"] == 0.25
    assert market_state(shocked, date(2024, 1, 4))["SPY"]["spread_multiplier"] == 3
    cfg = config(events=[events[1]])
    assert_frame_equal(stock_path(base, 0), stock_path(cfg, 0))
    no_random = dict(base.symbols[0].model_dump(), mu=0, realized_volatility=0)
    cfg = config(symbols=[no_random], events=[{**events[1], "implied_volatility": None, "realized_volatility": 0.5}])
    prices = stock_path(cfg, 0).close
    assert prices.iloc[1] != prices.iloc[0] and prices.iloc[-1] == prices.iloc[-2]


def test_contracts_survive_crash_without_lookahead():
    """暴跌后原来的远虚值合约仍然存在，新合约只能在冲击后上市。"""
    cfg = config()
    book = ContractBook(cfg.chain)
    before = book.list_contracts(date(2024, 1, 2), cfg.symbols[0], 100)
    additions = book.list_contracts(date(2024, 1, 3), cfg.symbols[0], 50)
    assert {c["contract_id"] for c in before} <= set(book.active)
    assert additions and min(c["listed_date"] for c in additions) == date(2024, 1, 3)
    assert len(book.active) == len(before) + len(additions)


def test_market_quotes_follow_shocks_and_spread_isolation():
    """冲击传递到真实期权链；只扩大价差时价格和 Greeks 保持一致。"""
    base = MonteCarloSource(config()).generate_path()
    wide_event = {
        "kind": "parameter_override",
        "start_date": "2024-01-03",
        "end_date": "2024-01-04",
        "symbols": ["SPY"],
        "spread_multiplier": 4,
    }
    wide = MonteCarloSource(config(events=[wide_event])).generate_path()
    fields = [name for name in base.options.columns if name not in ("bid", "ask")]
    assert_frame_equal(base.options[fields], wide.options[fields])
    assert (wide.options.ask - wide.options.bid >= base.options.ask - base.options.bid - 1e-10).all()
    market = MonteCarloSource(
        config(
            events=[
                {"kind": "price_shock", "date": "2024-01-03", "symbols": ["SPY"], "factor": 0.6},
                {**wide_event, "implied_volatility": 0.5},
            ]
        )
    ).generate_path()
    first = pd.Timestamp("2024-01-02")
    assert_frame_equal(
        base.options[base.options.quote_date == first], market.options[market.options.quote_date == first]
    )
    old = set(base.options.loc[base.options.quote_date == first, "contract_id"])
    crash_day = market.options[market.options.quote_date == pd.Timestamp("2024-01-03")]
    assert old <= set(crash_day.contract_id)
    assert crash_day.implied_volatility.eq(0.5).all()
    assert (
        market.options.loc[market.options.quote_date == pd.Timestamp("2024-01-05"), "implied_volatility"].eq(0.25).all()
    )


def test_closing_partial_generator_restores_quantlib_date():
    """调用方提前停止分片消费后可显式关闭，并继续其他路径。"""
    source = MonteCarloSource(config())
    original = ql.Settings.instance().evaluationDate
    iterator = source.iter_batches(0)
    next(iterator)
    iterator.close()
    assert ql.Settings.instance().evaluationDate == original
    source.generate_path(1)


def european_price(spot, strike, iv, rate, years, kind):
    """欧式解析公式仅用于独立参考测试，不作为生产定价器。"""

    def cdf(z):
        return (1 + math.erf(z / math.sqrt(2))) / 2

    d1 = (math.log(spot / strike) + (rate + iv**2 / 2) * years) / (iv * math.sqrt(years))
    d2 = d1 - iv * math.sqrt(years)
    if kind == "c":
        return spot * cdf(d1) - strike * math.exp(-rate * years) * cdf(d2)
    return strike * math.exp(-rate * years) * cdf(-d2) - spot * cdf(-d1)


@pytest.mark.parametrize("days,strike", [(1, 500), (3, 450), (30, 500), (365, 750), (730, 250)])
@pytest.mark.parametrize("kind", ["c", "p"])
def test_pricing_bounds_and_grid_convergence(days, strike, kind):
    """短期、长期、深实值和深虚值均满足参考精度。"""
    day = date(2024, 1, 2)
    expiry = day + timedelta(days=days)
    original_date = ql.Settings.instance().evaluationDate
    with AmericanPricer(PricingConfig(risk_free_rate=0.04)) as pricer:
        quote = pricer.price(day, expiry, 500, strike, 0.25, kind)
    with AmericanPricer(PricingConfig(risk_free_rate=0.04, time_grid=400, price_grid=800)) as pricer:
        reference = pricer.price(day, expiry, 500, strike, 0.25, kind)
    assert ql.Settings.instance().evaluationDate == original_date
    assert abs(quote["theoretical_price"] - reference["theoretical_price"]) <= max(
        0.01, reference["theoretical_price"] * 0.001
    )
    assert abs(quote["delta"] - reference["delta"]) <= 0.005
    european = european_price(500, strike, 0.25, 0.04, days / 365, kind)
    assert quote["theoretical_price"] >= european - max(0.01, european * 0.001)
    if kind == "c":
        assert abs(quote["theoretical_price"] - european) <= max(0.01, european * 0.001)


def test_quote_and_valuation_date_restore_on_error():
    """价差模型不改变理论价值，异常路径不会留下全局估值日期。"""
    price = 1.2345
    settings = QuoteConfig()
    normal, stressed = make_quote(price, settings), make_quote(price, settings, 5)
    assert stressed["bid"] <= normal["bid"] <= price <= normal["ask"] <= stressed["ask"]
    assert make_quote(0.00001, settings)["bid"] == 0
    original = ql.Settings.instance().evaluationDate
    with pytest.raises(RuntimeError), AmericanPricer(PricingConfig(risk_free_rate=0.04)) as pricer:
        pricer.price(date(2024, 1, 2), date(2024, 6, 21), 100, 100, 0.2, "c")
        raise RuntimeError("interrupted")
    assert ql.Settings.instance().evaluationDate == original


def test_exercise_boundary_greeks_and_cached_context_restore():
    """美式 Put 提前行权区域的 Greeks 不受原生插值噪声影响。"""
    pricer = AmericanPricer(PricingConfig(risk_free_rate=0.04))
    original = ql.Settings.instance().evaluationDate
    with pricer:
        result = pricer.price(date(2024, 1, 3), date(2024, 7, 19), 100, 130, 0.25, "p")
        assert abs(result["theoretical_price"] - 30) < 0.01
        assert abs(result["delta"] + 1) < 0.005
        assert abs(result["gamma"]) < 0.001
    with pricer:
        cached = pricer.price(date(2024, 1, 3), date(2024, 7, 19), 100, 130, 0.25, "p")
        assert ql.Settings.instance().evaluationDate == qdate(date(2024, 1, 3))
        assert cached == result
        with pytest.raises(RuntimeError, match="并发"), AmericanPricer(PricingConfig(risk_free_rate=0.04)):
            pass
    assert ql.Settings.instance().evaluationDate == original


@pytest.fixture(scope="module")
def small_path():
    """共享一条真实定价的小路径，避免重复昂贵求解。"""
    return MonteCarloSource(config()).generate_path(7)


def test_batch_size_path_order_and_adapter_copy(small_path):
    """分片大小、路径调用顺序和适配器使用不改变结果。"""
    source = MonteCarloSource(config(chunk_sessions=3))
    source.generate_path(1)
    repeated = source.generate_path(7)
    for name in TABLE_COLUMNS:
        assert_frame_equal(getattr(small_path, name), getattr(repeated, name))
    options, stock = repeated.for_symbol("SPY")
    assert "path_id" not in options and "path_id" not in stock
    options.loc[0, "bid"] = -1
    stock.loc[0, "close"] = -1
    assert repeated.options.bid.ge(0).all() and repeated.stock.close.gt(0).all()
    with pytest.raises(KeyError):
        repeated.for_symbol("QQQ")


def test_persistence_and_settlement(tmp_path):
    """到期内在价值单独保存，所有表精确往返。"""
    cfg = config(end_date="2024-01-08")
    source = MonteCarloSource(cfg)
    expected = source.generate_path(0)
    dataset = source.generate_to(tmp_path / "market")
    loaded = dataset.load_path(0)
    for name in TABLE_COLUMNS:
        assert_frame_equal(getattr(expected, name), getattr(loaded, name))
    assert not loaded.settlements.empty
    assert (loaded.options.quote_date < loaded.options.expiration).all()
    assert dataset.validate()["0"]["settlements"] == len(loaded.settlements)
    with pytest.raises(FileExistsError):
        source.generate_to(dataset.root)


def test_resume_failure_and_complete_path_is_untouched(tmp_path, monkeypatch):
    """恢复重建未完成路径，保持已完成文件不变。"""
    source = MonteCarloSource(config())
    dataset = source.generate_to(tmp_path / "market", path_ids=[1])
    file = next((dataset.root / "path-00000001").glob("options-*.parquet"))
    before = file.stat().st_mtime_ns
    original = source.iter_batches

    def interrupted(path_id):
        yield next(original(path_id))
        raise RuntimeError("人工中断")

    monkeypatch.setattr(source, "iter_batches", interrupted)
    with pytest.raises(RuntimeError, match="人工中断"):
        source.generate_to(dataset.root, path_ids=[0], resume=True)
    assert SimulationDataset.open(dataset.root).manifest["paths"]["0"]["status"] == "failed"
    monkeypatch.setattr(source, "iter_batches", original)
    dataset = source.generate_to(dataset.root, path_ids=[1, 0], resume=True)
    assert file.stat().st_mtime_ns == before
    assert_frame_equal(dataset.load_path(0).options, source.generate_path(0).options)
    changed = MonteCarloSource(config(seed=43))
    with pytest.raises(ValueError, match="不同"):
        changed.generate_to(dataset.root, resume=True)
    with writer_lock(dataset.root), pytest.raises(RuntimeError, match="写入进程"):
        source.generate_to(dataset.root, resume=True)


def test_corruption_and_missing_contract_quote_detected(tmp_path):
    """检测文件损坏，以及摘要正确但业务覆盖错误的数据。"""
    dataset = MonteCarloSource(config()).generate_to(tmp_path / "market")
    record = next(r for r in dataset.manifest["paths"]["0"]["files"] if r["table"] == "options")
    path = dataset.root / "path-00000000" / record["name"]
    original = path.read_bytes()
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="校验失败"):
        dataset.validate()
    path.write_bytes(original)
    frame = pd.read_parquet(path).iloc[1:]
    frame.to_parquet(path, index=False)
    record["sha256"], record["rows"] = checksum(path), len(frame)
    write_manifest(dataset.root, dataset.manifest)
    with pytest.raises(ValueError, match="不完整"):
        SimulationDataset.open(dataset.root).validate()


def test_unknown_directory_and_version_mismatch_are_preserved(tmp_path, monkeypatch):
    """恢复不覆盖清单外文件，且拒绝生成器版本变化。"""
    source = MonteCarloSource(config())
    dataset = source.generate_to(tmp_path / "market")
    unknown = dataset.root / "path-00000001"
    unknown.mkdir()
    owned_file = unknown / "user.txt"
    owned_file.write_text("保留", encoding="utf-8")
    with pytest.raises(FileExistsError, match="未登记"):
        source.generate_to(dataset.root, path_ids=[1], resume=True)
    assert owned_file.read_text(encoding="utf-8") == "保留"
    monkeypatch.setattr("options_strategies.simulation.storage.provenance", lambda: {})
    with pytest.raises(ValueError, match="版本不同"):
        source.generate_to(dataset.root, resume=True)


def test_cli(tmp_path):
    """生成、查看、验证及失败退出码均可通过 CLI 使用。"""
    settings = tmp_path / "config.json"
    settings.write_text(config().model_dump_json(), encoding="utf-8")
    root = tmp_path / "market"
    runner = CliRunner()
    args = ["generate", "--config", str(settings), "--output", str(root)]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["paths"] == {"0": "complete"}
    result = runner.invoke(main, ["inspect", "--input", str(root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["schema_version"] == 1
    result = runner.invoke(main, ["validate", "--input", str(root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["0"]["options"] > 0
    result = runner.invoke(main, args)
    assert result.exit_code == 1
    assert "已存在" in result.stderr and "Traceback" not in result.output
    result = runner.invoke(main, [*args, "--resume"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["paths"] == {"0": "complete"}


@pytest.mark.parametrize(
    "args,expected",
    [
        (["--help"], ["generate", "inspect", "validate"]),
        (["-h"], ["generate", "inspect", "validate"]),
        (["generate", "--help"], ["--config", "--output", "--resume"]),
        (["inspect", "--help"], ["--input"]),
        (["validate", "--help"], ["--input"]),
    ],
)
def test_cli_rich_help(args, expected):
    """主命令和子命令均展示富文本帮助及可发现的参数。"""
    result = CliRunner().invoke(main, args, terminal_width=100)
    assert result.exit_code == 0, result.output
    assert all(value in result.stdout for value in expected)
    assert "╭" in result.stdout and "╰" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["generate"],
        ["unknown"],
        ["inspect", "--input", "/nonexistent-simulation-input"],
        ["validate", "--input", "/nonexistent-simulation-input"],
    ],
)
def test_cli_usage_errors(args):
    """缺少参数、未知命令和无效输入路径使用 Click 的用法错误退出码。"""
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_cli_invalid_config_is_readable(tmp_path):
    """无效配置在错误面板中显示，不输出业务结果或异常堆栈。"""
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(main, ["generate", "--config", str(path), "--output", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "start_date" in result.stderr and "Traceback" not in result.output
    assert not (tmp_path / "out").exists()


@pytest.fixture(scope="module")
def benchmark_cli():
    """加载独立脚本的 Click 入口，不执行其主程序。"""
    script = Path(__file__).resolve().parents[3] / "scripts" / "benchmark_simulation.py"
    return runpy.run_path(str(script))["main"]


def test_benchmark_cli_help_and_validation(benchmark_cli, tmp_path):
    """性能命令也使用富文本帮助，并在计算前拒绝无效路径数。"""
    runner = CliRunner()
    result = runner.invoke(benchmark_cli, ["--help"])
    assert result.exit_code == 0
    assert all(option in result.stdout for option in ("--config", "--output", "--paths", "╭"))
    settings = tmp_path / "config.json"
    settings.write_text(config().model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        benchmark_cli, ["--config", str(settings), "--output", str(tmp_path / "out"), "--paths", "0"]
    )
    assert result.exit_code == 2
    assert not (tmp_path / "out").exists()


def test_benchmark_cli_generates_report(benchmark_cli, tmp_path):
    """Click 性能入口生成真实数据和报告，保留检查点输出。"""
    settings = tmp_path / "config with spaces.json"
    settings.write_text(config().model_dump_json(), encoding="utf-8")
    output = tmp_path / "benchmark with spaces"
    args = ["--config", str(settings), "--output", str(output), "--paths", "1"]
    result = CliRunner().invoke(benchmark_cli, args)
    assert result.exit_code == 0, result.output
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert report["paths"] == 1 and report["rows"]["options"] > 0
    assert report["peak_rss_bytes"] > 0 and '"checkpoint"' in result.stdout
    assert SimulationDataset.open(output).validate()["0"]["options"] == report["rows"]["options"]
    result = CliRunner().invoke(benchmark_cli, args)
    assert result.exit_code == 1 and "已存在" in result.stderr


def test_real_strategy_integration():
    """真实 optopsy 完成 PMCC 和 benchmark 成交，不使用模拟引擎替身。"""
    cfg = config(
        end_date="2024-03-01",
        pricing={"risk_free_rate": 0.04},
        symbols=[
            {
                "symbol": "SPY",
                "initial_price": 100,
                "mu": 0,
                "realized_volatility": 0,
                "implied_volatility": 0.25,
                "strike_step": 5,
            }
        ],
        chain={"weekly_expirations": 1, "monthly_expirations": 4, "strike_lower": 0.7, "strike_upper": 1.3},
    )
    market = MonteCarloSource(cfg).generate_path()
    options, stock = market.for_symbol("SPY")
    pmcc = run_pmcc(
        options,
        stock,
        PmccConfig(
            leaps_max_entry_dte=90,
            leaps_exit_dte=30,
            short_max_entry_dte=30,
            short_exit_dte=7,
            leaps_delta_min=0.6,
            leaps_delta_max=0.95,
            short_delta_min=0.1,
            short_delta_max=0.5,
        ),
    )
    assert pmcc.summary["total_trades"] > 0
    assert pmcc.leg_results["leaps"].summary["total_trades"] > 0
    assert pmcc.leg_results["short_call"].summary["total_trades"] > 0
    benchmark = run_benchmark(
        {"SPY": options},
        {"SPY": stock},
        BenchmarkConfig(
            symbols=["SPY"],
            max_entry_dte=90,
            exit_dte=30,
        ),
    )
    assert benchmark.summary["total_trades"] > 0
