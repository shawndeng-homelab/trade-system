"""Tests for the PMCC strategy config, class wiring, and state machine."""

from decimal import Decimal

from nautilus_trader.trading.strategy import Strategy
from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.strategy import PMCCState
from trade_system_strategies.pmcc.strategy import PMCCStrategy


# --- Config defaults -------------------------------------------------------------------


def test_pmcc_config_defaults():
    """Config defaults to standard PMCC parameters."""
    config = PMCCConfig(underlying="SPY.ARCA")
    assert config.leaps_target_delta == Decimal("0.80")
    assert config.short_target_delta == Decimal("0.30")
    assert config.leaps_quantity == Decimal("1")
    assert config.short_quantity == Decimal("1")
    assert config.leaps_min_dte == 60
    assert config.short_min_dte == 7
    assert config.leaps_roll_when_dte == 90
    assert config.leaps_roll_when_delta_below == Decimal("0.70")
    assert config.short_roll_dte == 7
    assert config.short_roll_pnl == Decimal("0.50")
    assert config.short_roll_min_pnl == Decimal("0.25")
    assert config.short_close_at_pnl == Decimal("0.90")
    assert config.short_always_roll_when_itm is True
    assert config.short_maintain_high_water_mark is True
    assert config.close_positions_on_stop is True
    assert config.bar_type is None


def test_pmcc_config_custom_values():
    """Config accepts custom values for all fields."""
    config = PMCCConfig(
        underlying="AAPL.NASDAQ",
        bar_type="AAPL.NASDAQ-1-MINUTE-LAST-EXTERNAL",
        leaps_target_delta=Decimal("0.75"),
        short_target_delta=Decimal("0.25"),
        leaps_min_dte=90,
        short_max_dte=30,
        short_roll_dte=5,
        short_close_at_pnl=Decimal("0.80"),
    )
    assert config.underlying == "AAPL.NASDAQ"
    assert config.bar_type == "AAPL.NASDAQ-1-MINUTE-LAST-EXTERNAL"
    assert config.leaps_target_delta == Decimal("0.75")
    assert config.short_target_delta == Decimal("0.25")
    assert config.leaps_min_dte == 90
    assert config.short_max_dte == 30


# --- Strategy construction ------------------------------------------------------------


def test_pmcc_strategy_is_strategy():
    """PMCCStrategy subclasses the NautilusTrader Strategy base."""
    assert issubclass(PMCCStrategy, Strategy)


def test_pmcc_strategy_constructs():
    """The strategy instantiates from its config."""
    strategy = PMCCStrategy(PMCCConfig(underlying="SPY.ARCA"))
    assert isinstance(strategy, Strategy)


def test_pmcc_strategy_initial_state_is_flat():
    """The strategy starts in the FLAT state."""
    strategy = PMCCStrategy(PMCCConfig(underlying="SPY.ARCA"))
    assert strategy._state == PMCCState.FLAT


def test_pmcc_strategy_roll_config_derived():
    """The roll config is derived from PMCCConfig on construction."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        short_roll_dte=5,
        short_roll_pnl=Decimal("0.40"),
    )
    strategy = PMCCStrategy(config)
    assert strategy._roll_config.dte == 5
    assert strategy._roll_config.pnl == Decimal("0.40")


# --- State machine enum ----------------------------------------------------------------


def test_pmcc_state_values():
    """All expected states exist in the PMCCState enum."""
    expected = {"FLAT", "ENTERING", "ACTIVE", "ROLLING_SHORT", "ROLLING_LEAPS", "EXITING"}
    actual = {state.value for state in PMCCState}
    assert actual == expected
