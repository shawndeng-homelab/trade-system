"""Hourly RSI double-touch mean-reversion backtest strategy.

Waits for the RSI to touch a band (upper for shorts, lower for longs) twice — with a
midline return between touches — then enters; closes when the RSI crosses back to the
midline. Decision logic lives in :mod:`~trade_system_strategies.rsi.signals`; position
sizing uses fractional Kelly from rolling realized-trade PnL
(:mod:`~trade_system_strategies.shared.sizing`).
"""



from decimal import Decimal

from nautilus_trader.common.enums import LogColor
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.indicators import RelativeStrengthIndex
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.trading.strategy import Strategy

from trade_system_strategies.rsi.config import RsiConfig
from trade_system_strategies.rsi.signals import RsiTouchState
from trade_system_strategies.rsi.signals import Signal
from trade_system_strategies.rsi.signals import update
from trade_system_strategies.shared.sizing import TradeStats
from trade_system_strategies.shared.sizing import drawdown_scalar


class RsiStrategy(Strategy):
    """Backtest strategy for the RSI double-touch mean-reversion rule.

    Args:
        config: The RSI strategy configuration.

    """

    def __init__(self, config: RsiConfig) -> None:
        """Initialize the RSI strategy, parsing ids and building the indicator."""
        super().__init__(config)
        self._config: RsiConfig = config

        self.instrument: Instrument = None
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.rsi = RelativeStrengthIndex(config.rsi_period)
        self.trend_ma = ExponentialMovingAverage(config.trend_ma_period) if config.use_trend_filter else None

        self._state = RsiTouchState(
            upper=config.upper_level,
            lower=config.lower_level,
            midline=config.midline,
        )
        self._stats = TradeStats(window=config.kelly_window, min_sample=config.kelly_min_sample)
        self._peak_equity: Decimal | None = None

    def on_start(self) -> None:
        """Resolve the instrument, register the RSI indicator, and subscribe to bars."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            self.stop()
            return

        self.register_indicator_for_bars(self.bar_type, self.rsi)
        if self.trend_ma is not None:
            self.register_indicator_for_bars(self.bar_type, self.trend_ma)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Drive entry/exit from the latest RSI reading on each bar close."""
        if not self.rsi.initialized:
            self.log.debug(
                f"Waiting for RSI warmup [{self.cache.bar_count(self.bar_type)}/{self._config.rsi_period}]",
                color=LogColor.BLUE,
            )
            return

        signal = update(self._state, self.rsi.value)

        # Trend filter: a mean-reversion long buys pullbacks (price often below the
        # MA), so longs are never filtered — only shorts are dropped when price is
        # above the MA (avoid fighting an uptrend). Exits are never filtered.
        if signal is Signal.OPEN_SHORT and self._is_counter_trend_short(bar):
            return

        if signal is Signal.OPEN_LONG:
            self._enter(OrderSide.BUY, bar)
        elif signal is Signal.OPEN_SHORT:
            self._enter(OrderSide.SELL, bar)
        elif signal in (Signal.CLOSE_LONG, Signal.CLOSE_SHORT):
            self.close_all_positions(self.instrument_id)

    def _is_counter_trend_short(self, bar: Bar) -> bool:
        """Return True if a short signal fights an uptrend (price above the MA)."""
        if self.trend_ma is None or not self.trend_ma.initialized:
            return False
        return bar.close.as_decimal() > self.trend_ma.value

    def on_position_closed(self, event) -> None:
        """Record the realized PnL and return of each closed trade into the accumulator."""
        pnl = event.realized_pnl.as_decimal()
        ret = Decimal(str(event.realized_return))
        self._stats.record(pnl, ret)
        self.log.info(
            f"Trade closed pnl={pnl} ret={ret} | stats: n={self._stats.count} "
            f"cont_kelly={self._stats.continuous_kelly_fraction(self._config.kelly_fraction, self._config.kelly_max_fraction)}",
            color=LogColor.YELLOW,
        )

    def on_stop(self) -> None:
        """Optionally flatten on stop."""
        if self._config.close_positions_on_stop:
            self.close_all_positions(self.instrument_id)

    def _enter(self, order_side: OrderSide, bar: Bar) -> None:
        """Submit a market order sized by Kelly (or fallback) to open a position."""
        order: MarketOrder = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=self._order_qty(bar),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _order_qty(self, bar: Bar) -> Quantity:
        """Size the order: fractional Kelly from rolling stats, floored to one increment."""
        size = self._target_size(bar)
        increment = self.instrument.size_increment.as_decimal()
        # make_qty raises if a sub-increment value rounds to zero; floor up to the
        # minimum tradeable size so a small account can still express the signal.
        if 0 < size < increment:
            size = increment
        return self.instrument.make_qty(size)

    def _target_size(self, bar: Bar) -> Decimal:
        """Return the intended share count before flooring to the size increment.

        Sizes by fractional Kelly (continuous ``mu/sigma^2`` or discrete win/loss) from
        rolling trade stats, scaled down by a drawdown factor during losing streaks.
        Falls back to a fixed fraction before ``kelly_min_sample`` or when edge is absent.
        """
        if not self._config.use_kelly_sizing:
            return self._config.trade_size
        equity = self._equity()
        if equity is None or equity <= 0:
            return self._config.trade_size
        price = bar.close.as_decimal()
        if price <= 0:
            return self._config.trade_size

        self._peak_equity = equity if self._peak_equity is None else max(self._peak_equity, equity)
        dd_scalar = drawdown_scalar(
            self._drawdown(equity),
            self._config.kelly_drawdown_max,
            self._config.kelly_drawdown_floor,
        )

        if not self._stats.ready:
            return self._scaled_size(equity, price, self._config.kelly_fallback_fraction, dd_scalar)

        kelly_fraction = self._kelly_fraction()
        if kelly_fraction <= 0:
            return self._scaled_size(equity, price, self._config.kelly_fallback_fraction, dd_scalar)
        return self._scaled_size(equity, price, kelly_fraction, dd_scalar)

    def _kelly_fraction(self) -> Decimal:
        """Return the Kelly fraction per the configured mode (continuous or discrete)."""
        if self._config.kelly_mode == "discrete":
            return self._stats.kelly_fraction(self._config.kelly_fraction, self._config.kelly_max_fraction)
        return self._stats.continuous_kelly_fraction(self._config.kelly_fraction, self._config.kelly_max_fraction)

    def _scaled_size(self, equity: Decimal, price: Decimal, fraction: Decimal, dd_scalar: Decimal) -> Decimal:
        """Apply the drawdown scalar to a fraction and convert to share count."""
        return (equity * fraction * dd_scalar) / price

    def _drawdown(self, equity: Decimal) -> Decimal:
        """Return the current drawdown fraction relative to peak equity."""
        if self._peak_equity is None or self._peak_equity <= 0:
            return Decimal("0")
        return Decimal("1") - (equity / self._peak_equity)

    def _equity(self) -> Decimal | None:
        """Return current account equity in the instrument's quote currency."""
        account = self.cache.account_for_venue(self.instrument_id.venue)
        if account is None:
            return None
        balance = account.balance_total(self.instrument.quote_currency)
        return balance.as_decimal() if balance is not None else None
