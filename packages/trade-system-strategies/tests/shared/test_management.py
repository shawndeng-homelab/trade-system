"""Tests for the roll/close decision rules in ``shared.management``."""

from decimal import Decimal

import pytest
from trade_system_strategies.shared.management import PositionSnapshot
from trade_system_strategies.shared.management import RollWhenConfig
from trade_system_strategies.shared.management import RollWhenLegConfig
from trade_system_strategies.shared.management import next_roll_strike_for_call
from trade_system_strategies.shared.management import next_roll_strike_for_put
from trade_system_strategies.shared.management import should_close
from trade_system_strategies.shared.management import should_roll


def _put(dte: int, pnl: Decimal, itm: bool | None = None, has_excess: bool = False) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        right="P",
        strike=Decimal("400"),
        spot=Decimal("405"),
        dte=dte,
        pnl=pnl,
        itm=itm,
        has_excess=has_excess,
    )


def _call(dte: int, pnl: Decimal, itm: bool | None = None, has_excess: bool = False) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        right="C",
        strike=Decimal("420"),
        spot=Decimal("405"),
        dte=dte,
        pnl=pnl,
        itm=itm,
        has_excess=has_excess,
    )


def _cfg(**overrides) -> RollWhenConfig:
    defaults: dict = {"dte": 7, "pnl": Decimal("0.5"), "min_pnl": Decimal("0.0")}
    defaults.update(overrides)
    return RollWhenConfig(**defaults)


# --- ITM / always_when_itm -----------------------------------------------------------


def test_roll_when_always_when_itm():
    """always_when_itm forces a roll even past the max_dte cap."""
    cfg = _cfg(max_dte=5, puts=RollWhenLegConfig(itm=False, always_when_itm=True))
    # put ITM (strike 400 <= spot? no -> 400 < 405 so put is OTM). Use strike above spot.
    put = PositionSnapshot("SPY", "P", Decimal("410"), Decimal("405"), dte=30, pnl=Decimal("0.1"))
    assert put.is_itm is True
    assert should_roll(put, cfg) is True


def test_no_roll_when_itm_and_itm_disabled_for_puts():
    """Puts default to itm=False, so an ITM put is not rolled (let it assign)."""
    cfg = _cfg()  # default puts.itm=False
    put = PositionSnapshot("SPY", "P", Decimal("410"), Decimal("405"), dte=3, pnl=Decimal("0.9"))
    assert put.is_itm is True
    assert should_roll(put, cfg) is False


def test_roll_itm_call_when_itm_enabled():
    """Calls default to itm=True, so an ITM covered call rolls."""
    cfg = _cfg()  # default calls.itm=True
    call = PositionSnapshot("SPY", "C", Decimal("400"), Decimal("405"), dte=3, pnl=Decimal("0.9"))
    assert call.is_itm is True
    assert should_roll(call, cfg) is True


# --- excess / max_dte ---------------------------------------------------------------


def test_no_roll_when_excess_and_has_excess_disabled():
    """An excess position is not rolled when has_excess is False."""
    cfg = _cfg(puts=RollWhenLegConfig(itm=False, has_excess=False))
    put = _put(dte=3, pnl=Decimal("0.9"), has_excess=True)
    assert should_roll(put, cfg) is False


def test_no_roll_past_max_dte():
    """max_dte caps rolling: a far-dated position is never rolled."""
    cfg = _cfg(max_dte=5)
    put = _put(dte=30, pnl=Decimal("0.9"))
    assert should_roll(put, cfg) is False


# --- DTE / profit triggers ----------------------------------------------------------


def test_roll_on_dte_trigger():
    """Near expiry with adequate profit triggers a roll via the DTE rule."""
    cfg = _cfg(min_pnl=Decimal("0.25"))
    put = _put(dte=3, pnl=Decimal("0.30"))
    assert should_roll(put, cfg) is True


def test_no_roll_on_dte_trigger_below_min_pnl():
    """Near expiry but below min_pnl does not roll on the DTE rule alone."""
    cfg = _cfg(min_pnl=Decimal("0.25"))
    put = _put(dte=3, pnl=Decimal("0.10"))
    # DTE rule fails (pnl < min_pnl); profit rule: 0.10 < 0.5 -> no roll.
    assert should_roll(put, cfg) is False


def test_roll_on_profit_trigger_regardless_of_dte():
    """Hitting the profit target rolls even with plenty of DTE left."""
    cfg = _cfg(pnl=Decimal("0.5"))
    put = _put(dte=30, pnl=Decimal("0.60"))
    assert should_roll(put, cfg) is True


# --- close -------------------------------------------------------------------------


def test_close_when_above_close_at_pnl():
    """A position past close_at_pnl (default 100%) is closed."""
    cfg = _cfg()
    put = _put(dte=10, pnl=Decimal("1.05"))
    assert should_close(put, cfg) is True


def test_no_close_at_exactly_close_at_pnl():
    """Equality is not enough; close requires pnl strictly above close_at_pnl."""
    cfg = _cfg()
    put = _put(dte=10, pnl=Decimal("1.0"))
    assert should_close(put, cfg) is False


def test_close_disabled_when_close_at_pnl_zero():
    """A falsy close_at_pnl disables the close-for-profit rule."""
    cfg = _cfg(close_at_pnl=Decimal("0"))
    put = _put(dte=10, pnl=Decimal("2.0"))
    assert should_close(put, cfg) is False


# --- ITM derivation ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("right", "strike", "spot", "expected"),
    [
        ("C", Decimal("400"), Decimal("405"), True),  # call ITM: strike <= spot
        ("C", Decimal("410"), Decimal("405"), False),  # call OTM
        ("P", Decimal("410"), Decimal("405"), True),  # put ITM: strike >= spot
        ("P", Decimal("400"), Decimal("405"), False),  # put OTM
    ],
)
def test_itm_derived_from_strike_spot(right, strike, spot, expected):
    """ITM is derived from right/strike/spot when not supplied explicitly."""
    pos = PositionSnapshot("SPY", right, strike, spot, dte=5, pnl=Decimal("0.1"))
    assert pos.is_itm is expected


# --- roll strike floors / ceilings -------------------------------------------------


def test_call_roll_strike_floored_at_cost_basis():
    """A covered-call roll strike cannot fall below the stock cost basis."""
    floor = next_roll_strike_for_call(
        short_strike=Decimal("400"),
        spot=Decimal("405"),
        stock_avg_cost=Decimal("420"),
    )
    assert floor == Decimal("420")


def test_call_roll_strike_high_water_mark():
    """Under HWM the roll strike never drops below the prior short strike."""
    floor = next_roll_strike_for_call(
        short_strike=Decimal("400"),
        spot=Decimal("405"),
        stock_avg_cost=Decimal("390"),
        maintain_high_water_mark=True,
        prior_short_strike=Decimal("415"),
    )
    assert floor == Decimal("415")


def test_call_roll_strike_honors_explicit_limit():
    """An explicit strike_limit is honored alongside the cost-basis floor."""
    floor = next_roll_strike_for_call(
        short_strike=Decimal("400"),
        spot=Decimal("405"),
        strike_limit=Decimal("430"),
    )
    assert floor == Decimal("430")


def test_put_roll_strike_ceiling_when_itm():
    """An ITM put roll caps the new strike at the prior short strike."""
    ceiling = next_roll_strike_for_put(
        short_strike=Decimal("410"),
        spot=Decimal("405"),
        prior_short_strike=Decimal("410"),
    )
    # strike 410 >= spot 405 -> ITM; ceiling capped at prior strike 410.
    assert ceiling == Decimal("410")


def test_put_roll_strike_ceiling_honors_limit():
    """An explicit strike ceiling is honored."""
    ceiling = next_roll_strike_for_put(
        short_strike=Decimal("410"),
        spot=Decimal("405"),
        strike_limit=Decimal("408"),
    )
    assert ceiling == Decimal("408")
