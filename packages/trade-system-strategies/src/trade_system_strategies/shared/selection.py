"""Option-leg selection helpers shared across strategies.

Pure functions over chain data (strike/delta/price). Both PMCC and backspread use
these to translate a chain slice into concrete :class:`~trade_system_strategies.shared.legs.LegSpec`
instances. Engine-free so they are unit-testable and reusable in research notebooks.
"""

from __future__ import annotations

from decimal import Decimal

from trade_system_strategies.shared.greeks import select_by_delta
from trade_system_strategies.shared.legs import LegSpec


def long_leg_by_delta(
    instrument_id: str,
    candidates: list[tuple[Decimal, Decimal]],
    target_delta: Decimal,
    quantity: Decimal,
    tolerance: Decimal | None = None,
) -> LegSpec | None:
    """Build a BUY leg on the candidate closest to ``target_delta``."""
    pick = select_by_delta(candidates, target_delta, tolerance)
    if pick is None:
        return None
    return LegSpec(instrument_id=instrument_id, side="BUY", quantity=quantity)


def short_leg_by_delta(
    instrument_id: str,
    candidates: list[tuple[Decimal, Decimal]],
    target_delta: Decimal,
    quantity: Decimal,
    tolerance: Decimal | None = None,
) -> LegSpec | None:
    """Build a SELL leg on the candidate closest to ``target_delta``."""
    pick = select_by_delta(candidates, target_delta, tolerance)
    if pick is None:
        return None
    return LegSpec(instrument_id=instrument_id, side="SELL", quantity=quantity)
