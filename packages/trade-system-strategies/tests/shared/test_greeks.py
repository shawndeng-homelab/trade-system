"""Tests for delta-based selection in ``shared.greeks``."""

from decimal import Decimal

from trade_system_strategies.shared.greeks import select_by_delta


def test_select_by_delta_picks_closest():
    """The candidate with delta nearest the target is chosen."""
    candidates = [
        (Decimal("400"), Decimal("0.82")),
        (Decimal("430"), Decimal("0.35")),
        (Decimal("440"), Decimal("0.22")),
    ]
    assert select_by_delta(candidates, Decimal("0.30")) == (Decimal("430"), Decimal("0.35"))


def test_select_by_delta_tolerance_filters():
    """Candidates outside the tolerance gap are skipped."""
    candidates = [
        (Decimal("400"), Decimal("0.82")),
        (Decimal("430"), Decimal("0.35")),
    ]
    # target 0.30, tolerance 0.02: 0.35 is gap 0.05 -> excluded; 0.82 gap 0.52 -> excluded
    assert select_by_delta(candidates, Decimal("0.30"), tolerance=Decimal("0.02")) is None


def test_select_by_delta_empty():
    """An empty candidate list yields no selection."""
    assert select_by_delta([], Decimal("0.30")) is None
