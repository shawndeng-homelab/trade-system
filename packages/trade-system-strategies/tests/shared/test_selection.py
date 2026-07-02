"""Tests for ``shared.selection`` leg builders."""

from decimal import Decimal

from trade_system_strategies.shared.selection import long_leg_by_delta
from trade_system_strategies.shared.selection import short_leg_by_delta


def test_long_leg_by_delta_builds_buy_leg():
    """A matching candidate yields a BUY leg with the requested quantity."""
    candidates = [(Decimal("400"), Decimal("0.82")), (Decimal("430"), Decimal("0.35"))]
    leg = long_leg_by_delta("LEAPS.ID", candidates, Decimal("0.80"), Decimal("1"))
    assert leg is not None
    assert leg.instrument_id == "LEAPS.ID"
    assert leg.side == "BUY"
    assert leg.quantity == Decimal("1")


def test_short_leg_by_delta_builds_sell_leg():
    """A matching candidate yields a SELL leg."""
    candidates = [(Decimal("400"), Decimal("0.82")), (Decimal("430"), Decimal("0.35"))]
    leg = short_leg_by_delta("SHORT.ID", candidates, Decimal("0.30"), Decimal("1"))
    assert leg is not None
    assert leg.side == "SELL"


def test_selection_returns_none_when_no_match():
    """When tolerance excludes everything, no leg is built."""
    candidates = [(Decimal("430"), Decimal("0.35"))]
    leg = long_leg_by_delta("LEAPS.ID", candidates, Decimal("0.80"), Decimal("1"), tolerance=Decimal("0.02"))
    assert leg is None
