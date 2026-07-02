"""PMCC-specific leg-selection logic (pure functions).

Shared between :mod:`~trade_system_strategies.pmcc.strategy` and research notebooks so
the selection used in a backtest is identical to the one explored in Jupyter.
"""

from __future__ import annotations

from decimal import Decimal

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.shared.legs import LegSpec
from trade_system_strategies.shared.selection import long_leg_by_delta
from trade_system_strategies.shared.selection import short_leg_by_delta


def select_pmcc_legs(
    config: PMCCConfig,
    leaps_candidates: list[tuple[Decimal, Decimal]],
    short_candidates: list[tuple[Decimal, Decimal]],
    leaps_instrument_id: str,
    short_instrument_id: str,
) -> tuple[LegSpec | None, LegSpec | None]:
    """Select the long LEAPS leg and the short near-term call leg for a PMCC.

    Args:
        config: The PMCC strategy config (target deltas, quantities, tolerance).
        leaps_candidates: ``(strike, delta)`` pairs from the far-expiry chain.
        short_candidates: ``(strike, delta)`` pairs from the near-term chain.
        leaps_instrument_id: Instrument id of the chosen LEAPS contract.
        short_instrument_id: Instrument id of the chosen short call.

    Returns:
        ``(leaps_leg, short_leg)``; either may be ``None`` if no candidate matched.

    """
    leaps_leg = long_leg_by_delta(
        leaps_instrument_id,
        leaps_candidates,
        config.leaps_target_delta,
        config.leaps_quantity,
    )
    short_leg = short_leg_by_delta(
        short_instrument_id,
        short_candidates,
        config.short_target_delta,
        config.short_quantity,
        config.short_delta_tolerance,
    )
    return leaps_leg, short_leg
