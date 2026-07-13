"""Tests for Black-Scholes delta approximation in ``shared.greeks``."""

from decimal import Decimal

from trade_system_strategies.shared.greeks import approx_call_delta
from trade_system_strategies.shared.greeks import approx_put_delta
from trade_system_strategies.shared.greeks import select_by_delta


# --- approx_call_delta ----------------------------------------------------------------


def test_deep_itm_call_has_delta_near_one():
    """A deep-ITM call should have delta close to 1.0."""
    delta = approx_call_delta(
        strike=Decimal("300"),
        spot=Decimal("400"),
        dte=180,
    )
    assert delta > Decimal("0.90")


def test_deep_otm_call_has_delta_near_zero():
    """A deep-OTM call should have low delta (below 0.20 with 25% vol)."""
    delta = approx_call_delta(
        strike=Decimal("600"),
        spot=Decimal("400"),
        dte=180,
    )
    assert delta < Decimal("0.20")


def test_atm_call_has_delta_near_half():
    """An ATM call should have delta around 0.50 (slightly above due to drift)."""
    delta = approx_call_delta(
        strike=Decimal("400"),
        spot=Decimal("400"),
        dte=180,
    )
    assert Decimal("0.45") < delta < Decimal("0.60")


def test_delta_decreases_as_dte_shrinks_for_otm():
    """OTM call delta decreases as expiry approaches."""
    long_dte = approx_call_delta(Decimal("430"), Decimal("400"), dte=180)
    short_dte = approx_call_delta(Decimal("430"), Decimal("400"), dte=7)
    assert long_dte > short_dte


def test_delta_zero_when_dte_zero():
    """Zero DTE returns delta 0 (edge case)."""
    delta = approx_call_delta(Decimal("400"), Decimal("400"), dte=0)
    assert delta == Decimal("0")


def test_delta_zero_when_spot_zero():
    """Zero spot returns delta 0 (edge case)."""
    delta = approx_call_delta(Decimal("400"), Decimal("0"), dte=30)
    assert delta == Decimal("0")


# --- approx_put_delta -----------------------------------------------------------------


def test_put_delta_is_call_delta_minus_one():
    """Put delta = call delta - 1."""
    put_delta = approx_put_delta(
        strike=Decimal("400"),
        spot=Decimal("400"),
        dte=180,
    )
    call_delta = approx_call_delta(
        strike=Decimal("400"),
        spot=Decimal("400"),
        dte=180,
    )
    assert put_delta == call_delta - Decimal("1")


def test_deep_itm_put_delta_near_minus_one():
    """A deep-ITM put has delta near -1."""
    delta = approx_put_delta(
        strike=Decimal("600"),
        spot=Decimal("400"),
        dte=180,
    )
    assert delta < Decimal("-0.80")


# --- select_by_delta (existing tests still valid) --------------------------------------


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
    assert select_by_delta(candidates, Decimal("0.30"), tolerance=Decimal("0.02")) is None


def test_select_by_delta_empty():
    """An empty candidate list yields no selection."""
    assert select_by_delta([], Decimal("0.30")) is None
