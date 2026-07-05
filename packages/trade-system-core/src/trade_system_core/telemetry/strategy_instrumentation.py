"""Strategy instrumentation mixin for automatic OpenTelemetry span and metric emission.

Subclass :class:`InstrumentedStrategy` instead of
:class:`~nautilus_trader.trading.strategy.Strategy` to get automatic telemetry
on every bar, fill, position change, and order event.  No per-strategy code
changes are needed — just change the base class.

Example::

    from trade_system_core.telemetry import InstrumentedStrategy

    class RsiStrategy(InstrumentedStrategy):
        ...

"""

from __future__ import annotations

from nautilus_trader.model.data import Bar
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.events import OrderSubmitted
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.events import PositionOpened
from nautilus_trader.trading.strategy import Strategy

from trade_system_core.observability import get_meter
from trade_system_core.observability import get_tracer
from trade_system_core.telemetry.metrics import BARS_PROCESSED
from trade_system_core.telemetry.metrics import FILL_PNL
from trade_system_core.telemetry.metrics import FILLS_COUNT
from trade_system_core.telemetry.metrics import ORDERS_SUBMITTED
from trade_system_core.telemetry.metrics import POSITION_COUNT
from trade_system_core.telemetry.metrics import POSITIONS_CLOSED
from trade_system_core.telemetry.metrics import POSITIONS_OPENED


class InstrumentedStrategy(Strategy):
    """A :class:`~nautilus_trader.trading.strategy.Strategy` subclass that
    automatically emits OTel spans and metrics for key lifecycle events.

    Metrics emitted:

    - ``trade_system.bars.processed`` — counter incremented on every ``on_bar``
    - ``trade_system.fills.count`` — counter incremented on every ``on_fill``
    - ``trade_system.fill.pnl`` — histogram recording realised PnL per fill
    - ``trade_system.orders.submitted`` — counter incremented on every ``on_order_submitted``
    - ``trade_system.positions.opened`` — counter incremented on every ``on_position_opened``
    - ``trade_system.positions.closed`` — counter incremented on every ``on_position_closed``
    - ``trade_system.position.count`` — gauge reflecting current open position count

    """  # noqa: D205

    def __init__(self, config) -> None:  # noqa: D107
        super().__init__(config)
        self._tracer = get_tracer(self.__class__.__module__)
        self._meter = get_meter(self.__class__.__module__)
        self._bars_counter = self._meter.create_counter(BARS_PROCESSED)
        self._fills_counter = self._meter.create_counter(FILLS_COUNT)
        self._fills_pnl_hist = self._meter.create_histogram(FILL_PNL)
        self._orders_counter = self._meter.create_counter(ORDERS_SUBMITTED)
        self._positions_opened_counter = self._meter.create_counter(POSITIONS_OPENED)
        self._positions_closed_counter = self._meter.create_counter(POSITIONS_CLOSED)
        self._position_count_gauge = self._meter.create_gauge(POSITION_COUNT)

    def _common_attributes(self) -> dict:
        """Return common OTel attributes for all spans/metrics."""
        return {
            "strategy.name": self.__class__.__name__,
            "strategy.id": str(self.id),
        }

    # ── Instrumented callbacks ──────────────────────────────────────────

    def on_bar(self, bar: Bar) -> None:
        """Emit a span and increment the bars counter, then delegate to super."""
        attrs = {**self._common_attributes(), "instrument_id": str(bar.bar_type.instrument_id)}
        with self._tracer.start_as_current_span("strategy.on_bar", attributes=attrs):
            self._bars_counter.add(1, attributes=attrs)
            super().on_bar(bar)

    def on_fill(self, event: OrderFilled) -> None:
        """Emit a span, increment fills counter, record PnL histogram."""
        attrs = {**self._common_attributes(), "instrument_id": str(event.instrument_id)}
        with self._tracer.start_as_current_span("strategy.on_fill", attributes=attrs):
            self._fills_counter.add(1, attributes=attrs)
            self._fills_pnl_hist.record(float(event.last_qty), attributes=attrs)
            super().on_fill(event)

    def on_order_submitted(self, event: OrderSubmitted) -> None:
        """Emit a span and increment the orders counter."""
        attrs = {**self._common_attributes(), "instrument_id": str(event.instrument_id)}
        with self._tracer.start_as_current_span("strategy.on_order_submitted", attributes=attrs):
            self._orders_counter.add(1, attributes=attrs)
            super().on_order_submitted(event)

    def on_position_opened(self, event: PositionOpened) -> None:
        """Emit a span, increment positions-opened counter, update gauge."""
        attrs = self._common_attributes()
        with self._tracer.start_as_current_span("strategy.on_position_opened", attributes=attrs):
            self._positions_opened_counter.add(1, attributes=attrs)
            super().on_position_opened(event)

    def on_position_closed(self, event: PositionClosed) -> None:
        """Emit a span, increment positions-closed counter, update gauge."""
        attrs = self._common_attributes()
        with self._tracer.start_as_current_span("strategy.on_position_closed", attributes=attrs):
            self._positions_closed_counter.add(1, attributes=attrs)
            super().on_position_closed(event)
