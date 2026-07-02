"""RSI double-touch strategy configuration."""



from decimal import Decimal

from nautilus_trader.config import StrategyConfig


class RsiConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`~trade_system_strategies.rsi.strategy.RsiStrategy`.

    Long when the RSI touches the lower band twice (with a midline return between), short
    when it touches the upper band twice; close when the RSI returns to the midline.

    Position sizing uses fractional Kelly derived from a rolling window of realized
    closed-trade PnL. Before ``kelly_min_sample`` trades are recorded, a fixed
    ``kelly_fallback_fraction`` of equity is used instead.

    Attributes:
        instrument_id: Underlying instrument id, e.g. ``"SPY.ARCA"``.
        bar_type: Bar type to trade on, e.g. ``"SPY.ARCA-1-HOUR-LAST-EXTERNAL"``.
        rsi_period: RSI lookback period.
        upper_level: Overbought threshold; two touches open a short.
        lower_level: Oversold threshold; two touches open a long.
        midline: Mean-reversion level; crossing it re-arms counting and closes positions.
        trade_size: Fallback fixed size (shares) used only when Kelly sizing is off or
            equity/price are unavailable.
        close_positions_on_stop: Close any open position when the strategy stops.
        use_trend_filter: If True, only take longs when price is above the trend MA and
            shorts when below it (drop counter-trend mean-reversion signals).
        trend_ma_period: EMA period for the trend filter.
        use_kelly_sizing: If True, size entries by fractional Kelly from rolling stats.
        kelly_mode: ``"continuous"`` (default, ``mu/sigma^2`` from per-trade returns) or
            ``"discrete"`` (win/loss payoff ratio).
        kelly_fraction: Scaling factor on full Kelly (``0.5`` = half-Kelly).
        kelly_max_fraction: Hard cap on the fraction of equity deployed per trade.
        kelly_min_sample: Closed trades required before Kelly sizing kicks in.
        kelly_window: Rolling window of trades for edge estimation (``None`` = all history).
        kelly_fallback_fraction: Fraction of equity used before ``kelly_min_sample`` is met.
        kelly_drawdown_max: Drawdown fraction at which exposure floors out (e.g. ``0.20``).
        kelly_drawdown_floor: Minimum drawdown scalar (``0`` stops new full-size entries).

    """

    instrument_id: str = "SPY.ARCA"
    bar_type: str = "SPY.ARCA-1-HOUR-LAST-EXTERNAL"
    rsi_period: int = 14
    upper_level: float = 0.70
    lower_level: float = 0.30
    midline: float = 0.50
    trade_size: Decimal = Decimal("100")
    close_positions_on_stop: bool = True
    use_trend_filter: bool = True
    trend_ma_period: int = 50
    use_kelly_sizing: bool = True
    kelly_mode: str = "continuous"
    kelly_fraction: Decimal = Decimal("0.5")
    kelly_max_fraction: Decimal | None = Decimal("0.5")
    kelly_min_sample: int = 10
    kelly_window: int | None = 30
    kelly_fallback_fraction: Decimal = Decimal("0.10")
    kelly_drawdown_max: Decimal = Decimal("0.20")
    kelly_drawdown_floor: Decimal = Decimal("0")
