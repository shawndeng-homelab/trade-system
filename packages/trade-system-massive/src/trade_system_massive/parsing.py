"""Conversions from Massive.com response models to Nautilus data objects.

The Massive/Polygon client returns typed model objects (``Agg``, ``Trade``,
``Quote``, ``LastTrade``, ``LastQuote``). These helpers convert them into the
Nautilus ``TradeTick`` / ``QuoteTick`` / ``Bar`` types.

All Massive timestamps are integers in nanoseconds **except** aggregate
timestamps, which are in milliseconds (a Polygon API convention); see
``_agg_ts_to_ns``.

The functions access attributes by name so unit tests can pass lightweight
fakes (e.g. ``types.SimpleNamespace``) instead of real Massive models.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity

from trade_system_massive.common import first_nonzero
from trade_system_massive.common import ms_to_ns


def _price(value: Any) -> Price:
    """Build a ``Price`` from a Massive numeric, preserving precision via ``str``."""
    return Price.from_str(str(value))


def _size(value: Any) -> Quantity:
    """Build a ``Quantity`` from a Massive numeric."""
    return Quantity.from_str(str(value))


def _tick_ts(sip_ns: int, participant_ns: int) -> int:
    """Pick the event timestamp from a trade/quote, preferring SIP over participant."""
    return first_nonzero(sip_ns, participant_ns)


def parse_trade_tick(instrument_id: InstrumentId, trade: Any) -> Any:
    """Convert a Massive ``Trade`` to a Nautilus ``TradeTick``.

    Massive/Polygon trades do not report aggressor side, so ``NO_AGGRESSOR``
    is used.

    """
    ts = _tick_ts(getattr(trade, "sip_timestamp", 0), getattr(trade, "participant_timestamp", 0))
    size = getattr(trade, "fractional_size", None) or getattr(trade, "size", 0)
    trade_id = TradeId(str(getattr(trade, "id", ""))) if getattr(trade, "id", None) else TradeId("-1")
    return TradeTick(
        instrument_id=instrument_id,
        price=_price(trade.price),
        size=_size(size),
        aggressor_side=AggressorSide.NO_AGGRESSOR,
        trade_id=trade_id,
        ts_event=ts,
        ts_init=ts,
    )


def parse_last_trade(instrument_id: InstrumentId, last: Any) -> Any:
    """Convert a Massive ``LastTrade`` to a Nautilus ``TradeTick``."""
    ts = _tick_ts(getattr(last, "sip_timestamp", 0), getattr(last, "participant_timestamp", 0))
    size = getattr(last, "fractional_size", None) or getattr(last, "size", 0)
    trade_id = TradeId(str(getattr(last, "id", ""))) if getattr(last, "id", None) else TradeId("-1")
    return TradeTick(
        instrument_id=instrument_id,
        price=_price(last.price),
        size=_size(size),
        aggressor_side=AggressorSide.NO_AGGRESSOR,
        trade_id=trade_id,
        ts_event=ts,
        ts_init=ts,
    )


def parse_quote_tick(instrument_id: InstrumentId, quote: Any) -> Any:
    """Convert a Massive ``Quote`` to a Nautilus ``QuoteTick``."""
    ts = _tick_ts(getattr(quote, "sip_timestamp", 0), getattr(quote, "participant_timestamp", 0))
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=_price(quote.bid_price),
        ask_price=_price(quote.ask_price),
        bid_size=_size(quote.bid_size),
        ask_size=_size(quote.ask_size),
        ts_event=ts,
        ts_init=ts,
    )


def parse_last_quote(instrument_id: InstrumentId, last: Any) -> Any:
    """Convert a Massive ``LastQuote`` to a Nautilus ``QuoteTick``."""
    ts = _tick_ts(getattr(last, "sip_timestamp", 0), getattr(last, "participant_timestamp", 0))
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=_price(last.bid_price),
        ask_price=_price(last.ask_price),
        bid_size=_size(last.bid_size),
        ask_size=_size(last.ask_size),
        ts_event=ts,
        ts_init=ts,
    )


_TIMESPAN_NS = {
    "second": 1_000_000_000,
    "minute": 60_000_000_000,
    "hour": 3_600_000_000_000,
    "day": 86_400_000_000_000,
}


def _agg_ts_to_ns(agg: Any, multiplier: int, timespan: str, on_close: bool) -> int:
    """Return the bar event timestamp in nanoseconds.

    Polygon/Massive aggregate ``timestamp`` is the bar **open** in milliseconds.
    When ``on_close`` is set, advance to the bar close (open + ``multiplier`` *
    timespan).

    """
    open_ms = int(getattr(agg, "timestamp", 0) or 0)
    open_ns = ms_to_ns(open_ms)
    if not on_close:
        return open_ns
    unit_ns = _TIMESPAN_NS.get(timespan, 0)
    return open_ns + int(multiplier) * unit_ns


def parse_bar(bar_type: BarType, agg: Any, multiplier: int, timespan: str, on_close: bool) -> Bar:
    """Convert a Massive ``Agg`` to a Nautilus ``Bar``."""
    ts_event = _agg_ts_to_ns(agg, multiplier, timespan, on_close)
    return Bar(
        bar_type=bar_type,
        open=_price(agg.open),
        high=_price(agg.high),
        low=_price(agg.low),
        close=_price(agg.close),
        volume=_size(getattr(agg, "volume", 0) or 0),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def parse_expiration_ns(expiration_date: Any) -> int:
    """Convert a Massive ``expiration_date`` (YYYY-MM-DD) to UTC nanoseconds at 16:00 ET.

    The 16:00 ET (20:00 UTC) close is the standard US equity option expiration
    time. Returns 0 if the date cannot be parsed.

    """
    if not expiration_date:
        return 0
    if isinstance(expiration_date, dt.date):
        d = expiration_date
    else:
        try:
            d = dt.date.fromisoformat(str(expiration_date))
        except ValueError:
            return 0
    # 20:00 UTC == 16:00 US/Eastern (approximate, ignores DST; good enough for v1).
    dt_utc = dt.datetime(d.year, d.month, d.day, 20, 0, tzinfo=dt.timezone.utc)
    return int(dt_utc.timestamp() * 1_000_000_000)


def decimal_or_default(value: Any, default: Decimal) -> Decimal:
    """Coerce `value` to ``Decimal`` or return `default` when falsy."""
    if value is None or value == "":
        return default
    return Decimal(str(value))
