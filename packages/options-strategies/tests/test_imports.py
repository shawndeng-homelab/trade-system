"""Verify public API imports work end-to-end."""

from options_strategies.pmcc import PmccConfig
from options_strategies.pmcc import leaps_entry_dates
from options_strategies.pmcc import run_pmcc
from options_strategies.pmcc.config import PmccConfig as ConfigDirect
from options_strategies.pmcc.signals import leaps_entry_dates as leaps_direct
from options_strategies.pmcc.strategy import run_pmcc as run_direct


def test_pmcc_config_defaults() -> None:
    """PmccConfig can be instantiated with only required defaults."""
    config = PmccConfig(symbol="SPY", capital=100_000.0)
    assert config.symbol == "SPY"
    assert config.capital == 100_000.0


def test_pmcc_config_custom() -> None:
    """PmccConfig accepts custom LEAPS and short-call parameters."""
    config = PmccConfig(
        symbol="SPY",
        capital=50_000.0,
        leaps_delta=0.85,
        short_delta=0.25,
        short_take_profit=0.8,
    )
    assert config.leaps_delta == 0.85
    assert config.short_delta == 0.25
    assert config.short_take_profit == 0.8


def test_api_aliases_match() -> None:
    """Top-level re-exports point to the same objects as the submodules."""
    assert PmccConfig is ConfigDirect
    assert run_pmcc is run_direct
    assert leaps_entry_dates is leaps_direct
