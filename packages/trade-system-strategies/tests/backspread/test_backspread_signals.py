"""Tests for backspread leg selection (pure functions, no engine)."""

from decimal import Decimal

from trade_system_strategies.backspread.config import BackspreadConfig
from trade_system_strategies.backspread.signals import select_backspread_legs


def test_select_backspread_legs_ratio():
    """The long leg carries `ratio` contracts against one short contract."""
    config = BackspreadConfig(underlying="SPY.ARCA")
    candidates = [
        (Decimal("420"), Decimal("0.50")),
        (Decimal("430"), Decimal("0.35")),
        (Decimal("440"), Decimal("0.22")),
    ]
    short_leg, long_leg = select_backspread_legs(config, candidates, "SHORT.ID", "LONG.ID")
    assert short_leg is not None
    assert short_leg.side == "SELL"
    assert short_leg.quantity == Decimal("1")
    assert long_leg is not None
    assert long_leg.side == "BUY"
    assert long_leg.quantity == Decimal("2")  # default ratio 2


def test_backspread_config_defaults():
    """Defaults target 0.5 short / 0.3 long with a 2:1 ratio."""
    config = BackspreadConfig(underlying="SPY.ARCA")
    assert config.short_target_delta == Decimal("0.50")
    assert config.long_target_delta == Decimal("0.30")
    assert config.ratio == 2
