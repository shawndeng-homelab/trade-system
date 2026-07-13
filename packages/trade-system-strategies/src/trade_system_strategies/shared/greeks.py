"""Greeks helpers wrapping NautilusTrader's ``GreeksCalculator``.

Thin convenience layer so strategies and research notebooks share one way to compute
per-leg and portfolio greeks. The engine-coupled ``GreeksCalculator`` lives behind
``self.greeks`` on a running strategy; here we expose pure helpers for the parts that
do not need an engine (leg-level Black-Scholes, delta lookup).
"""

import math
from decimal import Decimal


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation via ``math.erf``."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def approx_call_delta(
    strike: Decimal,
    spot: Decimal,
    dte: int,
    risk_free_rate: Decimal = Decimal("0.05"),
    volatility: Decimal = Decimal("0.25"),
) -> Decimal:
    """Approximate call delta using Black-Scholes d1 -> N(d1).

    NautilusTrader backtest does not compute greeks, so this pure-function
    approximation is used when pre-computed deltas are unavailable (e.g. when
    selecting LEAPS candidates from a catalog that lacks model greeks).

    Args:
        strike: Option strike price.
        spot: Current underlying price.
        dte: Days to expiry.
        risk_free_rate: Annualised risk-free rate (default 5%).
        volatility: Annualised implied volatility (default 25%).

    Returns:
        Approximate call delta as a ``Decimal`` in (0, 1).

    """
    if dte <= 0 or spot <= 0 or strike <= 0 or volatility <= 0:
        return Decimal("0")
    t = float(dte) / 365.0
    s = float(spot)
    k = float(strike)
    r = float(risk_free_rate)
    v = float(volatility)
    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * v * v) * t) / (v * sqrt_t)
    return Decimal(str(round(_norm_cdf(d1), 6)))


def approx_put_delta(
    strike: Decimal,
    spot: Decimal,
    dte: int,
    risk_free_rate: Decimal = Decimal("0.05"),
    volatility: Decimal = Decimal("0.25"),
) -> Decimal:
    """Approximate put delta as ``call_delta - 1`` via put-call parity.

    Args:
        strike: Option strike price.
        spot: Current underlying price.
        dte: Days to expiry.
        risk_free_rate: Annualised risk-free rate (default 5%).
        volatility: Annualised implied volatility (default 25%).

    Returns:
        Approximate put delta as a ``Decimal`` in (-1, 0).

    """
    return approx_call_delta(strike, spot, dte, risk_free_rate, volatility) - Decimal("1")


def select_by_delta(
    candidates: list[tuple[Decimal, Decimal]],
    target_delta: Decimal,
    tolerance: Decimal | None = None,
) -> tuple[Decimal, Decimal] | None:
    """Pick the candidate whose absolute delta is closest to ``target_delta``.

    Args:
        candidates: ``(strike, delta)`` pairs from an option chain slice.
        target_delta: The desired absolute delta (e.g. ``0.25`` for a 25-delta option).
        tolerance: Optional max acceptable ``abs(delta) - target_delta`` gap; candidates
            outside it are skipped. ``None`` means no tolerance filter.

    Returns:
        The ``(strike, delta)`` pair closest to the target, or ``None`` if none qualify.

    """
    best: tuple[Decimal, Decimal] | None = None
    best_gap: Decimal | None = None
    for strike, delta in candidates:
        gap = abs(abs(delta) - target_delta)
        if tolerance is not None and gap > tolerance:
            continue
        if best_gap is None or gap < best_gap:
            best = (strike, delta)
            best_gap = gap
    return best
