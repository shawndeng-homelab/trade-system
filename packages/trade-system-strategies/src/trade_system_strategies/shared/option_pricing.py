"""Option pricing and greeks via NautilusTrader's native Black-Scholes models.

Thin pure-function wrappers around :func:`nautilus_trader.model.greeks.black_scholes_greeks`
and :func:`nautilus_trader.model.greeks.imply_vol_and_greeks` that keep the interface
in ``Decimal`` / ``int`` / ``bool`` — no NautilusTrader types leak out, preserving the
engine-free constraint for unit testing and notebook reuse.

The existing :func:`~trade_system_strategies.shared.greeks.approx_call_delta` delegates
to :func:`bs_greeks` internally, so all strategies benefit from the accurate native
implementation automatically.
"""

from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model.greeks import black_scholes_greeks
from nautilus_trader.model.greeks import imply_vol_and_greeks


@dataclass(frozen=True)
class GreeksResult:
    """Full greeks snapshot for a single option leg.

    All values are ``Decimal`` for consistency with the rest of the strategy codebase.

    Attributes:
        delta: Option delta (0..1 for calls, -1..0 for puts).
        gamma: Option gamma (rate of change of delta).
        theta: Option theta (daily time decay, negative for longs).
        vega: Option vega (sensitivity to 1% change in implied vol).
        price: Theoretical option price.
        itm_prob: Risk-neutral probability of finishing ITM.
        vol: Implied volatility used (or solved for).

    """

    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    price: Decimal
    itm_prob: Decimal
    vol: Decimal


def bs_greeks(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    rate: Decimal = Decimal("0.05"),
    vol: Decimal = Decimal("0.25"),
    is_call: bool = True,
) -> GreeksResult:
    """Compute full Black-Scholes greeks for a European option.

    Wraps :func:`nautilus_trader.model.greeks.black_scholes_greeks` with ``Decimal``
    input/output.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        dte: Days to expiry.
        rate: Annualised risk-free rate (default 5%).
        vol: Annualised implied volatility (default 25%).
        is_call: ``True`` for calls, ``False`` for puts.

    Returns:
        A :class:`GreeksResult` with all greeks as ``Decimal``.

    """
    if dte <= 0 or spot <= 0 or strike <= 0 or vol <= 0:
        return GreeksResult(
            delta=Decimal("0"),
            gamma=Decimal("0"),
            theta=Decimal("0"),
            vega=Decimal("0"),
            price=Decimal("0"),
            itm_prob=Decimal("0"),
            vol=vol,
        )

    t = float(dte) / 365.0
    result = black_scholes_greeks(
        s=float(spot),
        r=float(rate),
        b=float(rate),  # cost of carry = risk-free rate for non-dividend paying
        vol=float(vol),
        is_call=is_call,
        k=float(strike),
        t=t,
    )
    return GreeksResult(
        delta=Decimal(str(round(result.delta, 8))),
        gamma=Decimal(str(round(result.gamma, 8))),
        theta=Decimal(str(round(result.theta, 8))),
        vega=Decimal(str(round(result.vega, 8))),
        price=Decimal(str(round(result.price, 8))),
        itm_prob=Decimal(str(round(result.itm_prob, 8))),
        vol=Decimal(str(round(result.vol, 8))),
    )


def bs_call_price(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    rate: Decimal = Decimal("0.05"),
    vol: Decimal = Decimal("0.25"),
) -> Decimal:
    """Compute the Black-Scholes price for a European call option.

    Args:
        spot: Current underlying price.
        strike: Call strike price.
        dte: Days to expiry.
        rate: Annualised risk-free rate.
        vol: Annualised implied volatility.

    Returns:
        Theoretical call price as ``Decimal``.

    """
    return bs_greeks(spot, strike, dte, rate, vol, is_call=True).price


def bs_put_price(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    rate: Decimal = Decimal("0.05"),
    vol: Decimal = Decimal("0.25"),
) -> Decimal:
    """Compute the Black-Scholes price for a European put option.

    Args:
        spot: Current underlying price.
        strike: Put strike price.
        dte: Days to expiry.
        rate: Annualised risk-free rate.
        vol: Annualised implied volatility.

    Returns:
        Theoretical put price as ``Decimal``.

    """
    return bs_greeks(spot, strike, dte, rate, vol, is_call=False).price


def implied_vol(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    rate: Decimal = Decimal("0.05"),
    is_call: bool = True,
    price: Decimal = Decimal("0"),
) -> Decimal:
    """Compute implied volatility from a market price.

    Wraps :func:`nautilus_trader.model.greeks.imply_vol_and_greeks`.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        dte: Days to expiry.
        rate: Annualised risk-free rate.
        is_call: ``True`` for calls, ``False`` for puts.
        price: Observed market price of the option.

    Returns:
        Implied volatility as ``Decimal``, or ``Decimal("0")`` if inversion fails.

    """
    if dte <= 0 or spot <= 0 or strike <= 0 or price <= 0:
        return Decimal("0")

    try:
        result = imply_vol_and_greeks(
            s=float(spot),
            r=float(rate),
            b=float(rate),
            is_call=is_call,
            k=float(strike),
            t=float(dte) / 365.0,
            price=float(price),
        )
        return Decimal(str(round(result.vol, 8)))
    except Exception:
        return Decimal("0")


def implied_vol_and_greeks(
    spot: Decimal,
    strike: Decimal,
    dte: int,
    rate: Decimal = Decimal("0.05"),
    is_call: bool = True,
    price: Decimal = Decimal("0"),
) -> GreeksResult:
    """Compute implied volatility and full greeks from a market price.

    Wraps :func:`nautilus_trader.model.greeks.imply_vol_and_greeks`.

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        dte: Days to expiry.
        rate: Annualised risk-free rate.
        is_call: ``True`` for calls, ``False`` for puts.
        price: Observed market price of the option.

    Returns:
        A :class:`GreeksResult` with implied vol and all greeks, or a zeroed result
        if the inversion fails.

    """
    if dte <= 0 or spot <= 0 or strike <= 0 or price <= 0:
        return GreeksResult(
            delta=Decimal("0"),
            gamma=Decimal("0"),
            theta=Decimal("0"),
            vega=Decimal("0"),
            price=price,
            itm_prob=Decimal("0"),
            vol=Decimal("0"),
        )

    try:
        result = imply_vol_and_greeks(
            s=float(spot),
            r=float(rate),
            b=float(rate),
            is_call=is_call,
            k=float(strike),
            t=float(dte) / 365.0,
            price=float(price),
        )
        return GreeksResult(
            delta=Decimal(str(round(result.delta, 8))),
            gamma=Decimal(str(round(result.gamma, 8))),
            theta=Decimal(str(round(result.theta, 8))),
            vega=Decimal(str(round(result.vega, 8))),
            price=Decimal(str(round(result.price, 8))),
            itm_prob=Decimal(str(round(result.itm_prob, 8))),
            vol=Decimal(str(round(result.vol, 8))),
        )
    except Exception:
        return GreeksResult(
            delta=Decimal("0"),
            gamma=Decimal("0"),
            theta=Decimal("0"),
            vega=Decimal("0"),
            price=price,
            itm_prob=Decimal("0"),
            vol=Decimal("0"),
        )
