"""Tests for PMCC leg selection (pure functions, no engine)."""

from decimal import Decimal

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.signals import select_pmcc_legs


def test_select_pmcc_legs_both_match():
    """Both legs are selected when candidates are within target deltas."""
    config = PMCCConfig(underlying="SPY.ARCA")
    leaps = [(Decimal("400"), Decimal("0.82")), (Decimal("410"), Decimal("0.70"))]
    short = [(Decimal("430"), Decimal("0.35")), (Decimal("440"), Decimal("0.22"))]
    long_leg, short_leg = select_pmcc_legs(config, leaps, short, "LEAPS.ID", "SHORT.ID")
    assert long_leg is not None
    assert long_leg.side == "BUY"
    assert long_leg.instrument_id == "LEAPS.ID"
    assert short_leg is not None
    assert short_leg.side == "SELL"
    assert short_leg.instrument_id == "SHORT.ID"


def test_select_pmcc_legs_short_unmatched():
    """A short leg outside tolerance is None while the LEAPS leg still resolves."""
    config = PMCCConfig(underlying="SPY.ARCA", short_delta_tolerance=Decimal("0.02"))
    leaps = [(Decimal("400"), Decimal("0.82"))]
    short = [(Decimal("430"), Decimal("0.35"))]  # gap 0.05 vs target 0.30
    long_leg, short_leg = select_pmcc_legs(config, leaps, short, "LEAPS.ID", "SHORT.ID")
    assert long_leg is not None
    assert short_leg is None
