"""Tiered-schedule lookup helpers used by venue fee tables.

Fee and financing schedules are expressed as ascending, immutable breakpoint tables
(for example VIP tiers keyed by 30-day volume, or IBKR monthly-volume tiers). These
helpers resolve the row that applies to a given lookup key without pulling in a heavy
dependency.
"""

from __future__ import annotations

from decimal import Decimal


def resolve_tier(thresholds: tuple[Decimal, ...], key: Decimal) -> int:
    """Return the index of the highest threshold that ``key`` reaches or exceeds.

    Args:
        thresholds: Ascending lower-bound thresholds for each tier (``thresholds[0]``
            should be 0).
        key: The lookup value (for example a 30-day traded notional).

    Returns:
        The zero-based tier index.

    """
    raise NotImplementedError("resolve_tier is implemented in a later step")
