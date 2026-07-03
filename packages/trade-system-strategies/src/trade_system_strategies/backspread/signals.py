"""Backspread-specific leg selection (pure functions)."""

from decimal import Decimal

from trade_system_strategies.backspread.config import BackspreadConfig
from trade_system_strategies.shared.legs import LegSpec
from trade_system_strategies.shared.selection import long_leg_by_delta
from trade_system_strategies.shared.selection import short_leg_by_delta


def select_backspread_legs(
    config: BackspreadConfig,
    candidates: list[tuple[Decimal, Decimal]],
    short_instrument_id: str,
    long_instrument_id: str,
) -> tuple[LegSpec | None, LegSpec | None]:
    """Select the short ATM/ITM leg and the long OTM legs for a call backspread.

    The long leg quantity is ``ratio`` contracts per short contract (default 2:1).

    Args:
        config: The backspread strategy config.
        candidates: ``(strike, delta)`` pairs from the option chain (same expiry).
        short_instrument_id: Instrument id of the chosen short call.
        long_instrument_id: Instrument id of the chosen long call.

    Returns:
        ``(short_leg, long_leg)``; either may be ``None`` if no candidate matched.

    """
    short_leg = short_leg_by_delta(
        short_instrument_id,
        candidates,
        config.short_target_delta,
        Decimal("1"),
        config.delta_tolerance,
    )
    long_leg = long_leg_by_delta(
        long_instrument_id,
        candidates,
        config.long_target_delta,
        Decimal(config.ratio),
        config.delta_tolerance,
    )
    return short_leg, long_leg
