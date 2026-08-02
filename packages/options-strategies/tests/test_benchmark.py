"""Verify benchmark public API imports work end-to-end."""

import pandas as pd
from options_strategies.benchmark import BenchmarkConfig
from options_strategies.benchmark import benchmark_entry_dates
from options_strategies.benchmark import run_benchmark
from options_strategies.benchmark.config import BenchmarkConfig as ConfigDirect
from options_strategies.benchmark.signals import benchmark_entry_dates as entry_direct
from options_strategies.benchmark.strategy import run_benchmark as run_direct


def test_benchmark_config_defaults() -> None:
    """BenchmarkConfig can be instantiated with only required defaults."""
    config = BenchmarkConfig()
    assert config.symbols == ["SPY", "QQQ", "IWM"]
    assert config.capital == 100_000.0
    assert config.delta_target == 0.50
    assert config.delta_min == 0.45
    assert config.delta_max == 0.55
    assert config.max_entry_dte == 730
    assert config.exit_dte == 150
    assert config.max_positions == 1


def test_benchmark_config_custom() -> None:
    """BenchmarkConfig accepts custom parameters."""
    config = BenchmarkConfig(
        symbols=["SPY"],
        capital=50_000.0,
        exit_dte=120,
        max_entry_dte=365,
    )
    assert config.symbols == ["SPY"]
    assert config.exit_dte == 120
    assert config.max_entry_dte == 365


def test_benchmark_config_frozen() -> None:
    """BenchmarkConfig is frozen (immutable)."""
    config = BenchmarkConfig()
    try:
        config.capital = 999  # type: ignore[misc]
    except Exception:
        pass
    else:
        msg = "Frozen config should reject attribute assignment"
        raise AssertionError(msg)


def test_api_aliases_match() -> None:
    """Top-level re-exports point to the same objects as the submodules."""
    assert BenchmarkConfig is ConfigDirect
    assert run_benchmark is run_direct
    assert benchmark_entry_dates is entry_direct


def _synthetic_stock() -> pd.DataFrame:
    """Build a minimal stock OHLCV DataFrame for signal tests."""
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    return pd.DataFrame(
        {
            "underlying_symbol": "TEST",
            "quote_date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
    )


def test_entry_dates_all_trading_days() -> None:
    """Benchmark entry dates include every trading day."""
    stock = _synthetic_stock()
    result = benchmark_entry_dates(stock)
    assert len(result) == 60
    assert list(result.columns) == ["underlying_symbol", "quote_date"]
