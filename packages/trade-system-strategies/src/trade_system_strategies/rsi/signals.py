"""RSI touch-count state machine (pure functions).

Decides when to open/close from an RSI value stream, engine-free so it can be unit-tested
and reused in research. Rule: a position opens only after the RSI touches the same band
(upper for shorts, lower for longs) twice, with the RSI returning to the midline between
touches to re-arm — this filters single-bar spikes. A position closes when the RSI returns
to the midline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    """Action returned by :func:`update` for one RSI reading."""

    NONE = 0
    OPEN_LONG = 1
    OPEN_SHORT = 2
    CLOSE_LONG = 3
    CLOSE_SHORT = 4


@dataclass
class RsiTouchState:
    """Mutable touch-count state for one RSI stream.

    Attributes:
        upper: Overbought threshold (open short on two touches).
        lower: Oversold threshold (open long on two touches).
        midline: Mean-reversion target; crossing it re-arms counting and closes positions.
        long_touches: Count of lower-band touches toward the current long signal.
        short_touches: Count of upper-band touches toward the current short signal.
        long_armed: Whether the next lower-band touch counts (requires a midline return first).
        short_armed: Whether the next upper-band touch counts (requires a midline return first).
        position: ``"LONG"``, ``"SHORT"``, or ``None`` when flat.

    """

    upper: float
    lower: float
    midline: float
    long_touches: int = 0
    short_touches: int = 0
    long_armed: bool = True
    short_armed: bool = True
    position: str | None = None


def update(state: RsiTouchState, rsi_value: float) -> Signal:
    """Advance the state with one RSI reading and return the resulting action.

    Touches are counted only while flat. After a touch the side disarms until the RSI
    crosses back past the midline, so two touches must be separated by a midline return.
    While in a position, a midline crossing closes it and re-arms counting.

    Args:
        state: The mutable touch-count state (updated in place).
        rsi_value: The latest RSI reading.

    Returns:
        The :class:`Signal` to act on this bar (``NONE`` if no action).

    """
    # Exit first: a midline crossing closes any open position. Closing at the midline
    # also re-arms that side, since we are flat again with the RSI already past midline.
    if state.position == "LONG" and rsi_value >= state.midline:
        state.position = None
        state.long_touches = 0
        state.long_armed = True
        return Signal.CLOSE_LONG
    if state.position == "SHORT" and rsi_value <= state.midline:
        state.position = None
        state.short_touches = 0
        state.short_armed = True
        return Signal.CLOSE_SHORT

    # Re-arm counting on a midline return while flat.
    if state.position is None:
        if rsi_value >= state.midline:
            state.long_armed = True
        if rsi_value <= state.midline:
            state.short_armed = True

        # Long signal: two armed lower-band touches.
        if rsi_value <= state.lower and state.long_armed:
            state.long_touches += 1
            state.long_armed = False
            if state.long_touches >= 2:
                state.long_touches = 0
                state.position = "LONG"
                return Signal.OPEN_LONG

        # Short signal: two armed upper-band touches.
        if rsi_value >= state.upper and state.short_armed:
            state.short_touches += 1
            state.short_armed = False
            if state.short_touches >= 2:
                state.short_touches = 0
                state.position = "SHORT"
                return Signal.OPEN_SHORT

    return Signal.NONE
