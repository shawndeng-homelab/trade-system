"""Tests for the ORB strategy config and class wiring."""

from decimal import Decimal

from nautilus_trader.trading.strategy import Strategy
from trade_system_strategies.orb.config import OrbConfig
from trade_system_strategies.orb.strategy import OrbStrategy


def test_orb_config_defaults():
    """Config defaults to SPY 1-minute bars, 30-min range, 0.1% buffer, ATR stop."""
    config = OrbConfig()
    assert config.instrument_id == "SPY.ARCX"
    assert config.bar_type == "SPY.ARCX-1-MINUTE-LAST-EXTERNAL"
    assert config.opening_range_minutes == 30
    assert config.breakout_buffer_pct == 0.001
    assert config.use_atr_stop is True
    assert config.atr_period == 14
    assert config.atr_stop_mult == 2.0
    assert config.fixed_stop_pct == 0.01
    assert config.use_time_exit is True
    assert config.exit_time == "15:45"
    assert config.trade_size == Decimal("100")
    assert config.close_positions_on_stop is True


def test_orb_strategy_is_strategy():
    """OrbStrategy subclasses the NautilusTrader Strategy base."""
    assert issubclass(OrbStrategy, Strategy)


def test_orb_strategy_constructs():
    """The strategy instantiates from its config and parses the ids."""
    strategy = OrbStrategy(OrbConfig())
    assert isinstance(strategy, Strategy)
    assert str(strategy.instrument_id) == "SPY.ARCX"
    assert str(strategy.bar_type) == "SPY.ARCX-1-MINUTE-LAST-EXTERNAL"
    assert strategy.atr.period == 14


def test_orb_strategy_no_atr_when_disabled():
    """When use_atr_stop is False, the ATR indicator is not created."""
    config = OrbConfig(use_atr_stop=False)
    strategy = OrbStrategy(config)
    assert strategy.atr is None
