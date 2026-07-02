"""Tests for the PMCC strategy config and class wiring."""

from decimal import Decimal

from nautilus_trader.trading.strategy import Strategy
from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.strategy import PMCCStrategy


def test_pmcc_config_defaults():
    """Config defaults to 0.8/0.3 delta legs with one contract each."""
    config = PMCCConfig(underlying="SPY.ARCA")
    assert config.leaps_target_delta == Decimal("0.80")
    assert config.short_target_delta == Decimal("0.30")
    assert config.leaps_quantity == Decimal("1")
    assert config.short_quantity == Decimal("1")


def test_pmcc_strategy_is_strategy():
    """PMCCStrategy subclasses the NautilusTrader Strategy base."""
    assert issubclass(PMCCStrategy, Strategy)


def test_pmcc_strategy_constructs():
    """The strategy instantiates from its config."""
    strategy = PMCCStrategy(PMCCConfig(underlying="SPY.ARCA"))
    assert isinstance(strategy, Strategy)
