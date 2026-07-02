"""Tests for ``shared.selection`` leg builders and the short-option selector."""

from decimal import Decimal

from trade_system_strategies.shared.selection import OptionCandidate
from trade_system_strategies.shared.selection import SelectionConfig
from trade_system_strategies.shared.selection import long_leg_by_delta
from trade_system_strategies.shared.selection import select_short_option
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


# --- select_short_option (full chain selector) ---------------------------------------


def _put(strike: float, dte: int, delta: float, mid: float, oi: int = 1000) -> OptionCandidate:
    return OptionCandidate(
        instrument_id=f"P{strike}",
        right="P",
        strike=Decimal(str(strike)),
        dte=dte,
        delta=Decimal(str(-delta)),  # put deltas are negative
        mid=Decimal(str(mid)),
        open_interest=oi,
    )


def _call(strike: float, dte: int, delta: float, mid: float, oi: int = 1000) -> OptionCandidate:
    return OptionCandidate(
        instrument_id=f"C{strike}",
        right="C",
        strike=Decimal(str(strike)),
        dte=dte,
        delta=Decimal(str(delta)),
        mid=Decimal(str(mid)),
        open_interest=oi,
    )


def test_select_put_prefers_shortest_dte_highest_delta():
    """Puts sort by abs(delta) desc then DTE asc: shortest-dated high-delta wins."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        spot=Decimal("400"),
    )
    chain = [
        _put(390, 7, 0.30, 2.0),  # nearest expiry, exactly at target
        _put(390, 14, 0.30, 3.0),  # same delta, further expiry
        _put(385, 7, 0.20, 1.5),  # lower delta
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.instrument_id == "P390"
    assert chosen.dte == 7


def test_select_call_prefers_shortest_dte_lowest_delta():
    """Calls sort by abs(delta) asc then DTE asc."""
    cfg = SelectionConfig(
        right="C",
        target_dte=7,
        target_delta=Decimal("0.30"),
        spot=Decimal("400"),
    )
    chain = [
        _call(410, 7, 0.30, 2.0),
        _call(410, 14, 0.30, 3.0),
        _call(415, 7, 0.20, 1.5),  # lower delta -> preferred among calls
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.instrument_id == "C415"


def test_select_filters_by_dte_window():
    """Expirations outside the DTE window are excluded."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        max_dte=30,
        spot=Decimal("400"),
    )
    chain = [
        _put(390, 5, 0.30, 2.0),  # below target_dte -> excluded
        _put(390, 35, 0.30, 2.0),  # above max_dte -> excluded
        _put(390, 10, 0.30, 2.0),  # in window
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.dte == 10


def test_select_filters_by_strike_limit_put():
    """A put strike_limit caps the ceiling."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        strike_limit=Decimal("395"),
        spot=Decimal("400"),
    )
    chain = [
        _put(400, 7, 0.30, 2.0),  # above limit -> excluded
        _put(390, 7, 0.30, 2.0),  # below limit -> ok
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.strike == Decimal("390")


def test_select_filters_by_minimum_price():
    """Premiums at or below minimum_price are excluded."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        minimum_price=Decimal("1.0"),
        spot=Decimal("400"),
    )
    chain = [
        _put(390, 7, 0.30, 1.0),  # == minimum -> excluded (strictly greater required)
        _put(385, 7, 0.30, 1.5),  # above minimum -> ok
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.mid == Decimal("1.5")


def test_select_filters_by_open_interest():
    """Candidates below minimum_open_interest are excluded."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        minimum_open_interest=500,
        spot=Decimal("400"),
    )
    chain = [
        _put(390, 7, 0.30, 2.0, oi=100),  # too thin -> excluded
        _put(385, 7, 0.30, 1.5, oi=1000),  # ok
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.open_interest == 1000


def test_select_excludes_high_delta():
    """A contract with abs(delta) above target_delta is rejected."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        spot=Decimal("400"),
    )
    chain = [
        _put(395, 7, 0.50, 3.0),  # too deep ITM -> excluded
        _put(390, 7, 0.30, 2.0),  # ok
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.instrument_id == "P390"


def test_select_returns_none_when_all_filtered():
    """No survivor yields None."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        minimum_price=Decimal("5.0"),
        spot=Decimal("400"),
    )
    chain = [_put(390, 7, 0.30, 2.0)]  # premium below minimum
    assert select_short_option(chain, cfg) is None


def test_select_fallback_uses_delta_rejects_when_premium_set():
    """With minimum_price > 0 and no delta-valid contract, delta-rejects retry."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        minimum_price=Decimal("1.0"),
        spot=Decimal("400"),
    )
    # Both above target delta (0.50, 0.45); fallback sorts by delta asc -> 0.45 first.
    chain = [
        _put(395, 7, 0.50, 3.0),
        _put(393, 7, 0.45, 2.5),
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.instrument_id == "P393"


def test_select_no_fallback_when_minimum_price_zero():
    """With minimum_price == 0 the fallback path is not taken."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        spot=Decimal("400"),
    )
    chain = [_put(395, 7, 0.50, 3.0)]  # delta too high, no fallback (min_price 0)
    assert select_short_option(chain, cfg) is None


def test_select_exclude_min_dte_for_forward_rolls():
    """exclude_min_dte drops expirations not strictly forward of the rolled leg."""
    cfg = SelectionConfig(
        right="P",
        target_dte=7,
        target_delta=Decimal("0.30"),
        exclude_min_dte=20,
        spot=Decimal("400"),
    )
    chain = [
        _put(390, 10, 0.30, 2.0),  # below exclude_min_dte -> excluded
        _put(390, 25, 0.30, 2.0),  # ok
    ]
    chosen = select_short_option(chain, cfg)
    assert chosen is not None
    assert chosen.dte == 25
