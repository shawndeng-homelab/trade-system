"""Tests for option pricing and greeks via NautilusTrader's native BS models."""

import math
from decimal import Decimal

from trade_system_strategies.shared.option_pricing import GreeksResult
from trade_system_strategies.shared.option_pricing import bs_call_price
from trade_system_strategies.shared.option_pricing import bs_greeks
from trade_system_strategies.shared.option_pricing import bs_put_price
from trade_system_strategies.shared.option_pricing import implied_vol
from trade_system_strategies.shared.option_pricing import implied_vol_and_greeks


# --- bs_greeks ------------------------------------------------------------------------


def test_deep_itm_call_delta_near_one():
    """A deep-ITM call should have delta close to 1.0."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("300"),
        dte=180,
        vol=Decimal("0.25"),
    )
    assert result.delta > Decimal("0.90")


def test_deep_otm_call_delta_near_zero():
    """A deep-OTM call should have delta close to 0.0."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("600"),
        dte=180,
        vol=Decimal("0.25"),
    )
    assert result.delta < Decimal("0.10")


def test_atm_call_delta_near_half():
    """An ATM call should have delta around 0.50."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("400"),
        dte=180,
        vol=Decimal("0.25"),
    )
    assert Decimal("0.45") < result.delta < Decimal("0.60")


def test_greeks_result_has_all_fields():
    """GreeksResult contains all expected fields with Decimal values."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
    )
    assert isinstance(result, GreeksResult)
    assert isinstance(result.delta, Decimal)
    assert isinstance(result.gamma, Decimal)
    assert isinstance(result.theta, Decimal)
    assert isinstance(result.vega, Decimal)
    assert isinstance(result.price, Decimal)
    assert isinstance(result.itm_prob, Decimal)
    assert isinstance(result.vol, Decimal)


def test_greeks_zero_dte_returns_zero():
    """Zero DTE returns a zeroed GreeksResult."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("400"),
        dte=0,
    )
    assert result.delta == Decimal("0")
    assert result.price == Decimal("0")


def test_put_greeks_negative_delta():
    """Put delta is negative."""
    result = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
        is_call=False,
    )
    assert result.delta < Decimal("0")


def test_greeks_put_call_parity():
    """Call delta - put delta should be approximately 1 (put-call parity)."""
    call = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
        is_call=True,
    )
    put = bs_greeks(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
        is_call=False,
    )
    assert abs(call.delta - put.delta - Decimal("1")) < Decimal("0.001")


# --- bs_call_price / bs_put_price -----------------------------------------------------


def test_call_price_positive():
    """Call price is positive for an OTM option."""
    price = bs_call_price(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
    )
    assert price > Decimal("0")


def test_deep_itm_call_price_near_intrinsic():
    """Deep ITM call price is close to intrinsic value (spot - strike)."""
    price = bs_call_price(
        spot=Decimal("400"),
        strike=Decimal("300"),
        dte=180,
        vol=Decimal("0.25"),
    )
    intrinsic = Decimal("400") - Decimal("300")
    # Price should be >= intrinsic (time value added)
    assert price >= intrinsic
    # And not too far above intrinsic for a deep ITM option
    assert price < intrinsic + Decimal("15")


def test_put_price_positive():
    """Put price is positive for an OTM put."""
    price = bs_put_price(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
    )
    assert price > Decimal("0")


def test_call_put_parity():
    """Call - put = spot - strike * exp(-r*t) (put-call parity)."""
    call = bs_call_price(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        rate=Decimal("0.05"),
        vol=Decimal("0.25"),
    )
    put = bs_put_price(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        rate=Decimal("0.05"),
        vol=Decimal("0.25"),
    )
    expected = Decimal("400") - Decimal("430") * Decimal(str(math.exp(-0.05 * 30 / 365)))
    assert abs((call - put) - expected) < Decimal("0.10")


# --- implied_vol ----------------------------------------------------------------------


def test_implied_vol_from_atm_price():
    """Implied vol can be recovered from a known BS price."""
    # Compute a price at 25% vol, then recover the vol
    price = bs_call_price(
        spot=Decimal("400"),
        strike=Decimal("400"),
        dte=30,
        vol=Decimal("0.25"),
    )
    iv = implied_vol(
        spot=Decimal("400"),
        strike=Decimal("400"),
        dte=30,
        is_call=True,
        price=price,
    )
    assert abs(iv - Decimal("0.25")) < Decimal("0.02")


def test_implied_vol_zero_price_returns_zero():
    """Zero price returns zero vol."""
    iv = implied_vol(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        price=Decimal("0"),
    )
    assert iv == Decimal("0")


# --- implied_vol_and_greeks -----------------------------------------------------------


def test_implied_vol_and_greeks_returns_full_result():
    """implied_vol_and_greeks returns a full GreeksResult."""
    price = bs_call_price(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        vol=Decimal("0.25"),
    )
    result = implied_vol_and_greeks(
        spot=Decimal("400"),
        strike=Decimal("430"),
        dte=30,
        is_call=True,
        price=price,
    )
    assert isinstance(result, GreeksResult)
    assert result.vol > Decimal("0")
    assert result.delta > Decimal("0")
    assert result.price > Decimal("0")
