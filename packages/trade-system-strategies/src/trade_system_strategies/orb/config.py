"""Opening Range Breakout (ORB) strategy configuration."""

from decimal import Decimal

from nautilus_trader.config import StrategyConfig


class OrbConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`~trade_system_strategies.orb.strategy.OrbStrategy`.

    The Opening Range Breakout strategy captures intraday trends by waiting for price to
    break out of the first *N* minutes' range (the "opening range"). A long is triggered
    when price exceeds the range high by a buffer percentage; a short when it falls below
    the range low by the same buffer. The buffer filters false breakouts from noise.

    Exits use an ATR-based trailing stop when enabled, or a simple percentage stop.
    Position sizing is fixed at ``trade_size`` shares/contracts per trade.

    Attributes:
        instrument_id: Underlying instrument id, e.g. ``"SPY.ARCX"``.
        bar_type: Bar type to trade on, e.g. ``"SPY.ARCX-1-MINUTE-LAST-EXTERNAL"``.
        opening_range_minutes: Number of minutes from session open that define the
            opening range. Common values: 15, 30, 60.
        breakout_buffer_pct: Minimum percentage move beyond the range high/low to
            confirm a breakout (e.g. 0.001 = 0.1%). Filters noise.
        use_atr_stop: If True, use ATR-based trailing stop for exits; otherwise use
            a fixed percentage stop from entry.
        atr_period: ATR lookback period (used only when ``use_atr_stop`` is True).
        atr_stop_mult: Multiplier on ATR for the trailing stop distance.
            A 2× ATR stop means the stop trails by 2× ATR from the best price.
        fixed_stop_pct: Fixed percentage stop-loss from entry price, used when
            ``use_atr_stop`` is False.
        use_time_exit: If True, close any open position at a specified time of day
            (e.g. before the close to avoid overnight risk for day-session instruments).
        exit_time: Time of day (``"HH:MM"`` format) at which to flatten, in the
            instrument's venue timezone.
        trade_size: Fixed size (shares/contracts) per trade.
        close_positions_on_stop: Close any open position when the strategy stops.

    """

    instrument_id: str = "SPY.ARCX"
    bar_type: str = "SPY.ARCX-1-MINUTE-LAST-EXTERNAL"
    opening_range_minutes: int = 30
    breakout_buffer_pct: float = 0.001
    use_atr_stop: bool = True
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    fixed_stop_pct: float = 0.01
    use_time_exit: bool = True
    exit_time: str = "15:45"
    trade_size: Decimal = Decimal("100")
    close_positions_on_stop: bool = True
