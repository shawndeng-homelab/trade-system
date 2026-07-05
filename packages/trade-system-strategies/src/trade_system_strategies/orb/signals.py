"""Opening Range Breakout state machine (pure functions).

Decides when to open/close positions based on the opening range breakout rule,
engine-free so it can be unit-tested and reused in research. The opening range is
defined as the high and low of the first *N* bars of each trading day. A breakout
occurs when price moves beyond the range by a buffer percentage. Exits use an
ATR-based trailing stop or a fixed percentage stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    """Action returned by :func:`update` for one bar."""

    NONE = 0
    OPEN_LONG = 1
    OPEN_SHORT = 2
    CLOSE_LONG = 3
    CLOSE_SHORT = 4


@dataclass
class OrbState:
    """Mutable state for the Opening Range Breakout signal generator.

    Attributes:
        range_high: High of the opening range (``None`` until the range is established).
        range_low: Low of the opening range (``None`` until the range is established).
        range_established: Whether the opening range period has completed.
        bars_in_range: Count of bars processed within the current opening range period.
        opening_range_bars: Total bars that define the opening range.
        breakout_buffer_pct: Minimum percentage beyond the range to confirm a breakout.
        position: ``"LONG"``, ``"SHORT"``, or ``None`` when flat.
        entry_price: Price at which the current position was entered.
        best_price: Best price seen since entry (for trailing stop).
        atr_value: Current ATR value (``None`` if ATR stop is not used).
        atr_stop_mult: Multiplier on ATR for trailing stop distance.
        fixed_stop_pct: Fixed percentage stop from entry (used when ATR is unavailable).
        use_atr_stop: Whether to use ATR-based trailing stop.
        current_day: Trading day identifier for daily reset (``None`` initially).

    """

    range_high: float | None = None
    range_low: float | None = None
    range_established: bool = False
    bars_in_range: int = 0
    opening_range_bars: int = 30
    breakout_buffer_pct: float = 0.001
    position: str | None = None
    entry_price: float | None = None
    best_price: float | None = None
    atr_value: float | None = None
    atr_stop_mult: float = 2.0
    fixed_stop_pct: float = 0.01
    use_atr_stop: bool = True
    current_day: str | None = None


def _new_day(state: OrbState) -> OrbState:
    """Reset the state for a new trading day.

    Clears the opening range, position tracking, and range-establishment flag.
    Retains configuration parameters (opening_range_bars, buffer, stop settings).

    Args:
        state: The current state to reset.

    Returns:
        A fresh state with the same configuration but cleared range and position data.

    """
    return OrbState(
        opening_range_bars=state.opening_range_bars,
        breakout_buffer_pct=state.breakout_buffer_pct,
        atr_stop_mult=state.atr_stop_mult,
        fixed_stop_pct=state.fixed_stop_pct,
        use_atr_stop=state.use_atr_stop,
    )


def update(
    state: OrbState,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    day: str,
    atr_value: float | None = None,
) -> Signal:
    """Advance the state with one bar and return the resulting action.

    During the opening range period, bars accumulate to set the range high/low.
    After the range is established, a breakout beyond the range (with buffer) triggers
    an entry. While in a position, a trailing stop (ATR or fixed) monitors for exits.
    A new day resets everything.

    Args:
        state: The mutable ORB state (updated in place).
        bar_high: High price of the current bar.
        bar_low: Low price of the current bar.
        bar_close: Close price of the current bar.
        day: Trading day identifier (e.g. ``"2026-01-02"``) for daily reset.
        atr_value: Current ATR reading (``None`` if not available or not used).

    Returns:
        The :class:`Signal` to act on this bar (``NONE`` if no action).

    """
    # --- Daily reset ---
    if state.current_day is not None and day != state.current_day:
        signal = Signal.NONE
        if state.position == "LONG":
            signal = Signal.CLOSE_LONG
        elif state.position == "SHORT":
            signal = Signal.CLOSE_SHORT
        # Reset state for the new day
        new = _new_day(state)
        state.range_high = new.range_high
        state.range_low = new.range_low
        state.range_established = new.range_established
        state.bars_in_range = new.bars_in_range
        state.position = new.position
        state.entry_price = new.entry_price
        state.best_price = new.best_price
        state.current_day = day
        # If we closed a position on the day boundary, return that signal
        # (the new day's range building starts on the next call)
        if signal is not Signal.NONE:
            return signal

    if state.current_day is None:
        state.current_day = day

    # Update ATR
    state.atr_value = atr_value

    # --- Build opening range ---
    if not state.range_established:
        if state.range_high is None or bar_high > state.range_high:
            state.range_high = bar_high
        if state.range_low is None or bar_low < state.range_low:
            state.range_low = bar_low
        state.bars_in_range += 1
        if state.bars_in_range >= state.opening_range_bars:
            state.range_established = True
        return Signal.NONE

    # --- Range is established: check for signals ---
    assert state.range_high is not None
    assert state.range_low is not None

    # Check trailing stop exit first
    if state.position is not None:
        return _check_exit(state, bar_close)

    # Check breakout entry
    buffer_up = state.range_high * (1 + state.breakout_buffer_pct)
    buffer_down = state.range_low * (1 - state.breakout_buffer_pct)

    if bar_close > buffer_up:
        state.position = "LONG"
        state.entry_price = bar_close
        state.best_price = bar_close
        return Signal.OPEN_LONG

    if bar_close < buffer_down:
        state.position = "SHORT"
        state.entry_price = bar_close
        state.best_price = bar_close
        return Signal.OPEN_SHORT

    return Signal.NONE


def _check_exit(state: OrbState, bar_close: float) -> Signal:
    """Check whether the trailing stop or fixed stop has been hit.

    For a long position, the stop trails below the best price by
    ``atr_stop_mult * ATR`` (or ``fixed_stop_pct * entry_price`` as fallback).
    For a short position, the stop trails above the best price.

    Args:
        state: The mutable ORB state (updated in place).
        bar_close: Close price of the current bar.

    Returns:
        ``CLOSE_LONG`` or ``CLOSE_SHORT`` if the stop is hit, ``NONE`` otherwise.

    """
    if state.position == "LONG":
        if bar_close > state.best_price:
            state.best_price = bar_close
        stop_price = _trailing_stop_price(state, side="LONG")
        if bar_close <= stop_price:
            state.position = None
            state.entry_price = None
            state.best_price = None
            return Signal.CLOSE_LONG

    elif state.position == "SHORT":
        if bar_close < state.best_price:
            state.best_price = bar_close
        stop_price = _trailing_stop_price(state, side="SHORT")
        if bar_close >= stop_price:
            state.position = None
            state.entry_price = None
            state.best_price = None
            return Signal.CLOSE_SHORT

    return Signal.NONE


def _trailing_stop_price(state: OrbState, side: str) -> float:
    """Calculate the trailing stop price.

    Uses ATR-based stop when ``use_atr_stop`` is True and ATR is available;
    otherwise falls back to a fixed percentage stop from the entry price.

    Args:
        state: The current ORB state.
        side: ``"LONG"`` or ``"SHORT"``.

    Returns:
        The stop price level.

    """
    if state.use_atr_stop and state.atr_value is not None and state.atr_value > 0:
        distance = state.atr_stop_mult * state.atr_value
    else:
        # Fallback: fixed percentage stop from entry
        assert state.entry_price is not None
        distance = state.fixed_stop_pct * state.entry_price

    if side == "LONG":
        return state.best_price - distance
    return state.best_price + distance
