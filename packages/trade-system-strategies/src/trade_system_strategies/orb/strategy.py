"""Intraday Opening Range Breakout (ORB) backtest strategy.

Waits for the first *N* minutes of the session to establish an opening range, then
enters long on a breakout above the range high (with buffer) or short on a breakout
below the range low. Exits via ATR trailing stop or fixed percentage stop. Decision
logic lives in :mod:`~trade_system_strategies.orb.signals`.
"""

from nautilus_trader.common.enums import LogColor
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.trading.strategy import Strategy

from trade_system_strategies.orb.config import OrbConfig
from trade_system_strategies.orb.signals import OrbState
from trade_system_strategies.orb.signals import Signal
from trade_system_strategies.orb.signals import update


class OrbStrategy(Strategy):
    """Backtest strategy for the Opening Range Breakout intraday trend rule.

    Args:
        config: The ORB strategy configuration.

    """

    def __init__(self, config: OrbConfig) -> None:
        """Initialize the ORB strategy, parsing ids and building indicators."""
        super().__init__(config)
        self._config: OrbConfig = config

        self.instrument: Instrument = None
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.atr = AverageTrueRange(config.atr_period) if config.use_atr_stop else None

        self._state = OrbState(
            opening_range_bars=config.opening_range_minutes,
            breakout_buffer_pct=config.breakout_buffer_pct,
            atr_stop_mult=config.atr_stop_mult,
            fixed_stop_pct=config.fixed_stop_pct,
            use_atr_stop=config.use_atr_stop,
        )

    def on_start(self) -> None:
        """Resolve the instrument, register indicators, and subscribe to bars."""
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.instrument_id}")
            self.stop()
            return

        if self.atr is not None:
            self.register_indicator_for_bars(self.bar_type, self.atr)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Drive entry/exit from the opening range breakout signal on each bar close."""
        # Wait for ATR warmup if ATR stop is enabled
        if self.atr is not None and not self.atr.initialized:
            self.log.debug(
                f"Waiting for ATR warmup [{self.cache.bar_count(self.bar_type)}/{self._config.atr_period}]",
                color=LogColor.BLUE,
            )
            return

        day = unix_nanos_to_dt(bar.ts_event).strftime("%Y-%m-%d")
        atr_val = self.atr.value if self.atr is not None and self.atr.initialized else None

        # Time-based exit: flatten before the configured exit time
        if self._config.use_time_exit and self._is_exit_time(bar):
            if self.portfolio.is_flat(self.instrument_id):
                return
            self.log.info(f"Time exit triggered at {bar.ts_event}", color=LogColor.YELLOW)
            self.close_all_positions(self.instrument_id)
            return

        signal = update(
            state=self._state,
            bar_high=float(bar.high),
            bar_low=float(bar.low),
            bar_close=float(bar.close),
            day=day,
            atr_value=atr_val,
        )

        if signal is Signal.OPEN_LONG:
            self._enter(OrderSide.BUY, bar)
        elif signal is Signal.OPEN_SHORT:
            self._enter(OrderSide.SELL, bar)
        elif signal in (Signal.CLOSE_LONG, Signal.CLOSE_SHORT):
            self.close_all_positions(self.instrument_id)

    def _is_exit_time(self, bar: Bar) -> bool:
        """Return True if the current bar time is at or past the configured exit time."""
        bar_time = unix_nanos_to_dt(bar.ts_event).strftime("%H:%M")
        return bar_time >= self._config.exit_time

    def on_position_closed(self, event) -> None:
        """Log the realized PnL of each closed trade."""
        pnl = event.realized_pnl.as_decimal()
        self.log.info(f"Trade closed pnl={pnl}", color=LogColor.YELLOW)

    def on_stop(self) -> None:
        """Optionally flatten on stop."""
        if self._config.close_positions_on_stop:
            self.close_all_positions(self.instrument_id)

    def _enter(self, order_side: OrderSide, bar: Bar) -> None:
        """Submit a market order with fixed size to open a position."""
        order: MarketOrder = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=order_side,
            quantity=self._order_qty(),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _order_qty(self) -> Quantity:
        """Return the fixed trade size, floored to one size increment."""
        size = self._config.trade_size
        increment = self.instrument.size_increment.as_decimal()
        if 0 < size < increment:
            size = increment
        return self.instrument.make_qty(size)
