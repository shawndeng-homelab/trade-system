"""Tests for the RSI strategy config and class wiring."""

from decimal import Decimal

from nautilus_trader.trading.strategy import Strategy
from trade_system_strategies.rsi.config import RsiConfig
from trade_system_strategies.rsi.strategy import RsiStrategy


def test_rsi_config_defaults():
    """Config defaults to SPY hourly, 14-period RSI, 0.70/0.30/0.50 bands, Kelly sizing on."""
    config = RsiConfig()
    assert config.instrument_id == "SPY.ARCA"
    assert config.bar_type == "SPY.ARCA-1-HOUR-LAST-EXTERNAL"
    assert config.rsi_period == 14
    assert config.upper_level == 0.70
    assert config.lower_level == 0.30
    assert config.midline == 0.50
    assert config.trade_size == Decimal("100")
    assert config.close_positions_on_stop is True
    assert config.use_trend_filter is True
    assert config.trend_ma_period == 50
    assert config.use_kelly_sizing is True
    assert config.kelly_mode == "continuous"
    assert config.kelly_fraction == Decimal("0.5")
    assert config.kelly_max_fraction == Decimal("0.5")
    assert config.kelly_min_sample == 10
    assert config.kelly_window == 30
    assert config.kelly_fallback_fraction == Decimal("0.10")
    assert config.kelly_drawdown_max == Decimal("0.20")
    assert config.kelly_drawdown_floor == Decimal("0")


def test_rsi_strategy_is_strategy():
    """RsiStrategy subclasses the NautilusTrader Strategy base."""
    assert issubclass(RsiStrategy, Strategy)


def test_rsi_strategy_constructs():
    """The strategy instantiates from its config and parses the ids."""
    strategy = RsiStrategy(RsiConfig())
    assert isinstance(strategy, Strategy)
    assert str(strategy.instrument_id) == "SPY.ARCA"
    assert str(strategy.bar_type) == "SPY.ARCA-1-HOUR-LAST-EXTERNAL"
    assert strategy.rsi.period == 14
