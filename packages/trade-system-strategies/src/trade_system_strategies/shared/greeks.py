"""Greeks helpers wrapping NautilusTrader's ``GreeksCalculator``.

Thin convenience layer so strategies and research notebooks share one way to compute
per-leg and portfolio greeks. The engine-coupled ``GreeksCalculator`` lives behind
``self.greeks`` on a running strategy; here we expose pure helpers for the parts that
do not need an engine (leg-level Black-Scholes, delta lookup).
"""

from decimal import Decimal


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
