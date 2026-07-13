"""Greeks helpers wrapping NautilusTrader's native Black-Scholes models.

Thin convenience layer so strategies and research notebooks share one way to compute
per-leg and portfolio greeks. The heavy lifting is done by
:func:`nautilus_trader.model.greeks.black_scholes_greeks`; this module keeps the
``Decimal``-based interface and preserves the engine-free constraint for unit testing
and notebook reuse.
"""

from decimal import Decimal

from trade_system_strategies.shared.option_pricing import bs_greeks


def approx_call_delta(
    strike: Decimal,
    spot: Decimal,
    dte: int,
    risk_free_rate: Decimal = Decimal("0.05"),
    volatility: Decimal = Decimal("0.25"),
) -> Decimal:
    """Compute call delta via NautilusTrader's native Black-Scholes model.

    Delegates to :func:`~trade_system_strategies.shared.option_pricing.bs_greeks`
    for accurate results (replaces the former hand-rolled ``math.erf`` approximation).

    Args:
        strike: Option strike price.
        spot: Current underlying price.
        dte: Days to expiry.
        risk_free_rate: Annualised risk-free rate (default 5%).
        volatility: Annualised implied volatility (default 25%).

    Returns:
        Call delta as a ``Decimal`` in (0, 1).

    """
    return bs_greeks(spot, strike, dte, risk_free_rate, volatility, is_call=True).delta


def approx_put_delta(
    strike: Decimal,
    spot: Decimal,
    dte: int,
    risk_free_rate: Decimal = Decimal("0.05"),
    volatility: Decimal = Decimal("0.25"),
) -> Decimal:
    """Compute put delta as ``call_delta - 1`` via put-call parity.

    Args:
        strike: Option strike price.
        spot: Current underlying price.
        dte: Days to expiry.
        risk_free_rate: Annualised risk-free rate (default 5%).
        volatility: Annualised implied volatility (default 25%).

    Returns:
        Put delta as a ``Decimal`` in (-1, 0).

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
