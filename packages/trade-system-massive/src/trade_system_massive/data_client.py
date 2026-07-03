"""Live (historical-REST) data client for the Massive.com (Polygon-compatible) API.

The Massive ``RESTClient`` is synchronous (urllib3-based); every call is wrapped through
:func:`~trade_system_massive.rate_limiter.rate_limited_call`, which acquires a token from
the adapter's token-bucket limiter and runs the call in a worker thread.

v1 scope is **historical REST only**: ``_request_trade_ticks`` / ``_request_quote_ticks``
/ ``_request_bars`` / ``_request_instrument`` / ``_request_instruments`` /
``_request_order_book_snapshot`` are implemented; the ``subscribe`` / ``unsubscribe``
family raises ``NotImplementedError`` (real-time WebSocket streaming is planned for v2).
"""

import asyncio

from massive import RESTClient
from massive.exceptions import BadResponse
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.data.messages import RequestBars
from nautilus_trader.data.messages import RequestInstrument
from nautilus_trader.data.messages import RequestInstruments
from nautilus_trader.data.messages import RequestOrderBookSnapshot
from nautilus_trader.data.messages import RequestQuoteTicks
from nautilus_trader.data.messages import RequestTradeTicks
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import BookOrder
from nautilus_trader.model.data import OrderBookDelta
from nautilus_trader.model.enums import BookAction
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import ClientId

from trade_system_massive.common import bar_type_to_aggs_params
from trade_system_massive.common import date_to_str
from trade_system_massive.common import instrument_id_to_ticker
from trade_system_massive.common import ns_to_ms
from trade_system_massive.constants import MASSIVE
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.parsing import parse_bar
from trade_system_massive.parsing import parse_last_quote
from trade_system_massive.parsing import parse_quote_tick
from trade_system_massive.parsing import parse_trade_tick
from trade_system_massive.rate_limiter import TokenBucketRateLimiter
from trade_system_massive.rate_limiter import rate_limited_call


class MassiveDataClient(LiveMarketDataClient):
    """NautilusTrader data client for Massive.com (historical REST, v1).

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        The event loop for the client.
    msgbus : MessageBus
        The message bus for the client.
    cache : Cache
        The cache for the client.
    clock : LiveClock
        The clock for the client.
    instrument_provider : MassiveInstrumentProvider
        The Massive instrument provider.
    config : MassiveDataClientConfig
        The client configuration.
    name : str, optional
        A custom client ID override.

    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider,
        config,
        name: str | None = None,
    ) -> None:
        """Initialize the client, sharing the provider's REST client and limiter."""
        super().__init__(
            loop=loop,
            client_id=ClientId(name or MASSIVE),
            venue=None,  # Multi-venue (equities + OPRA options)
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )

        self._config = config
        self._instrument_provider: MassiveInstrumentProvider = instrument_provider
        self._client: RESTClient = instrument_provider._client
        self._rate_limiter: TokenBucketRateLimiter = instrument_provider._rate_limiter

        self._bars_timestamp_on_close: bool = config.bars_timestamp_on_close
        self._pagination_limit: int = config.pagination_limit
        self._max_retries: int = config.max_retries

    # ------------------------------------------------------------------ lifecycle

    async def _connect(self) -> None:
        await self._instrument_provider.initialize()
        # Push every loaded instrument (and its currency) into the data engine.
        for instrument in self._instrument_provider.get_all().values():
            self._handle_data(instrument)

    async def _disconnect(self) -> None:
        # The Massive REST client is connectionless (urllib3 pool, no persistent
        # socket); there is nothing to close in v1. In-flight `to_thread` calls will
        # be abandoned with the loop shutdown.
        return

    # ------------------------------------------------------------------ helpers

    def _time_range_params(self, request) -> dict:
        """Map a request's ns start/end to Massive ``timestamp_gte``/``timestamp_lte``.

        Massive accepts ms-integer timestamps for the trades/quotes endpoints. When
        only one bound is set, only that bound is passed.

        """
        params: dict = {}
        if request.start is not None:
            params["timestamp_gte"] = ns_to_ms(int(request.start))
        if request.end is not None:
            params["timestamp_lte"] = ns_to_ms(int(request.end))
        return params

    # ------------------------------------------------------------------ requests

    async def _request_trade_ticks(self, request: RequestTradeTicks) -> None:
        instrument_id = request.instrument_id
        ticker = instrument_id_to_ticker(instrument_id)
        params = self._time_range_params(request)
        if request.limit:
            params["limit"] = request.limit
        try:
            trades = await rate_limited_call(
                self._rate_limiter,
                self._client.list_trades,
                ticker,
                max_retries=self._max_retries,
                **params,
            )
        except BadResponse as exc:
            self._log.error(f"Cannot request trade ticks for {instrument_id}: {exc}")
            return
        ticks = [parse_trade_tick(instrument_id, t) for t in trades]
        self._handle_trade_ticks(
            instrument_id,
            ticks,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_quote_ticks(self, request: RequestQuoteTicks) -> None:
        instrument_id = request.instrument_id
        ticker = instrument_id_to_ticker(instrument_id)
        params = self._time_range_params(request)
        if request.limit:
            params["limit"] = request.limit
        try:
            quotes = await rate_limited_call(
                self._rate_limiter,
                self._client.list_quotes,
                ticker,
                max_retries=self._max_retries,
                **params,
            )
        except BadResponse as exc:
            self._log.error(f"Cannot request quote ticks for {instrument_id}: {exc}")
            return
        ticks = [parse_quote_tick(instrument_id, q) for q in quotes]
        self._handle_quote_ticks(
            instrument_id,
            ticks,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_bars(self, request: RequestBars) -> None:
        bar_type = request.bar_type
        if not bar_type.is_externally_aggregated():
            self._log.error(f"Cannot request {bar_type} bars: only EXTERNAL aggregation available from Massive")
            return
        if bar_type.spec.price_type != PriceType.LAST:
            self._log.error(f"Cannot request {bar_type} bars: only LAST price type available from Massive")
            return

        instrument_id = bar_type.instrument_id
        ticker = instrument_id_to_ticker(instrument_id)
        multiplier, timespan = bar_type_to_aggs_params(bar_type)
        from_ = date_to_str(request.start)
        to = date_to_str(request.end)
        try:
            aggs = await rate_limited_call(
                self._rate_limiter,
                self._client.list_aggs,
                ticker,
                multiplier,
                timespan,
                from_,
                to,
                max_retries=self._max_retries,
                limit=self._pagination_limit,
            )
        except BadResponse as exc:
            self._log.error(f"Cannot request bars for {bar_type}: {exc}")
            return
        bars = [parse_bar(bar_type, a, multiplier, timespan, self._bars_timestamp_on_close) for a in aggs]
        self._handle_bars(
            bar_type=bar_type,
            bars=bars,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_instrument(self, request: RequestInstrument) -> None:
        instrument = self._instrument_provider.find(request.instrument_id)
        if instrument is None:
            await self._instrument_provider.load_ids_async([request.instrument_id])
            instrument = self._instrument_provider.find(request.instrument_id)
        if instrument is None:
            self._log.error(f"Cannot find instrument for {request.instrument_id}")
            return
        self._handle_instrument(
            instrument,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_instruments(self, request: RequestInstruments) -> None:
        all_instruments = self._instrument_provider.get_all()
        target = [i for i in all_instruments.values() if i.venue == request.venue]
        self._handle_instruments(
            request.venue,
            target,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    async def _request_order_book_snapshot(self, request: RequestOrderBookSnapshot) -> None:
        """Build a 1-level book snapshot from the Massive last quote.

        NautilusTrader's data-client layer has no ``_handle_order_book_snapshot``
        callback, so the snapshot is delivered as a pair of ``OrderBookDelta`` messages
        (a ``CLEAR`` followed by ``SET`` for the bid and ask) via the standard deltas
        callback. This is a v1 best-effort path; a full depth snapshot is TODO.

        """
        instrument_id = request.instrument_id
        ticker = instrument_id_to_ticker(instrument_id)
        try:
            last_quote = await rate_limited_call(
                self._rate_limiter,
                self._client.get_last_quote,
                ticker,
                max_retries=self._max_retries,
            )
        except BadResponse as exc:
            self._log.error(f"Cannot request order book snapshot for {instrument_id}: {exc}")
            return
        quote = parse_last_quote(instrument_id, last_quote)
        ts = quote.ts_event
        # BookOrder requires Price/Quantity; reuse the parsed quote's values.
        bid_order = BookOrder(OrderSide.BUY, quote.bid_price, quote.bid_size, ts)
        ask_order = BookOrder(OrderSide.SELL, quote.ask_price, quote.ask_size, ts)
        deltas = [
            OrderBookDelta(instrument_id, BookAction.CLEAR, None, 0, ts, ts),
            OrderBookDelta(instrument_id, BookAction.SET, bid_order, 0, ts, ts),
            OrderBookDelta(instrument_id, BookAction.SET, ask_order, 0, ts, ts),
        ]
        self._handle_order_book_deltas(
            instrument_id,
            deltas,
            correlation_id=request.id,
            start=request.start,
            end=request.end,
            params=request.params,
        )

    # ------------------------------------------------------------------ streaming (v2)

    async def _subscribe_trade_ticks(self, command) -> None:
        raise NotImplementedError("Real-time trade-tick streaming is planned for v2")

    async def _subscribe_quote_ticks(self, command) -> None:
        raise NotImplementedError("Real-time quote-tick streaming is planned for v2")

    async def _subscribe_bars(self, command) -> None:
        raise NotImplementedError("Real-time bar streaming is planned for v2")

    async def _subscribe_instrument(self, command) -> None:
        raise NotImplementedError("Real-time instrument streaming is planned for v2")

    async def _subscribe_instruments(self, command) -> None:
        raise NotImplementedError("Real-time instrument streaming is planned for v2")

    async def _unsubscribe_trade_ticks(self, command) -> None:
        raise NotImplementedError("Real-time trade-tick streaming is planned for v2")

    async def _unsubscribe_quote_ticks(self, command) -> None:
        raise NotImplementedError("Real-time quote-tick streaming is planned for v2")

    async def _unsubscribe_bars(self, command) -> None:
        raise NotImplementedError("Real-time bar streaming is planned for v2")
