"""Tests for the RSI touch-count state machine (pure functions, no engine)."""

from trade_system_strategies.rsi.signals import RsiTouchState
from trade_system_strategies.rsi.signals import Signal
from trade_system_strategies.rsi.signals import update


def _state() -> RsiTouchState:
    """Fresh state with the default 0.70/0.30/0.50 bands (nautilus RSI is 0..1)."""
    return RsiTouchState(upper=0.70, lower=0.30, midline=0.50)


def test_no_signal_before_two_touches():
    """A single lower-band touch produces no entry."""
    s = _state()
    assert update(s, 0.25) is Signal.NONE
    assert s.long_touches == 1
    assert s.position is None


def test_two_lower_touches_without_midline_return_do_not_open():
    """Two touches without re-arming at the midline do not count as a second."""
    s = _state()
    update(s, 0.25)  # first touch, disarms long
    assert update(s, 0.20) is Signal.NONE  # still disarmed -> not counted
    assert s.long_touches == 1
    assert s.position is None


def test_two_lower_touches_with_midline_return_open_long():
    """Touch, return to midline, touch again -> OPEN_LONG."""
    s = _state()
    update(s, 0.25)  # first touch
    update(s, 0.55)  # midline return re-arms
    assert update(s, 0.28) is Signal.OPEN_LONG
    assert s.position == "LONG"


def test_two_upper_touches_with_midline_return_open_short():
    """Symmetric upper-band path -> OPEN_SHORT."""
    s = _state()
    update(s, 0.75)  # first touch
    update(s, 0.45)  # midline return re-arms short
    assert update(s, 0.72) is Signal.OPEN_SHORT
    assert s.position == "SHORT"


def test_long_closes_on_midline_cross_up():
    """An open long closes when the RSI returns to/above the midline."""
    s = _state()
    update(s, 0.25)
    update(s, 0.55)
    update(s, 0.28)  # OPEN_LONG
    assert update(s, 0.51) is Signal.CLOSE_LONG
    assert s.position is None


def test_short_closes_on_midline_cross_down():
    """An open short closes when the RSI returns to/below the midline."""
    s = _state()
    update(s, 0.75)
    update(s, 0.45)
    update(s, 0.72)  # OPEN_SHORT
    assert update(s, 0.49) is Signal.CLOSE_SHORT
    assert s.position is None


def test_no_counting_while_in_position():
    """Bars while a position is open (and not crossing the midline) do not count."""
    s = _state()
    update(s, 0.25)
    update(s, 0.55)
    update(s, 0.28)  # OPEN_LONG
    # 0.40 is below the midline, so the long is not closed; counting stays suspended.
    assert update(s, 0.40) is Signal.NONE
    assert s.short_touches == 0
    assert s.long_touches == 0
    assert s.position == "LONG"


def test_resets_after_close_and_can_reenter():
    """After closing, a fresh two-touch sequence opens again."""
    s = _state()
    update(s, 0.25)
    update(s, 0.55)
    update(s, 0.28)  # OPEN_LONG
    update(s, 0.51)  # CLOSE_LONG
    # New cycle
    update(s, 0.22)  # first touch
    assert update(s, 0.55) is Signal.NONE  # re-arm
    assert update(s, 0.27) is Signal.OPEN_LONG


def test_mid_within_band_does_nothing():
    """RSI sitting in the neutral zone produces no signal."""
    s = _state()
    for value in (0.45, 0.50, 0.55):
        assert update(s, value) is Signal.NONE
    assert s.position is None
    assert s.long_touches == 0
    assert s.short_touches == 0
