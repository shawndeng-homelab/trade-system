"""Tests for the Massive futures parsing helpers.

Parsing is tested directly with ``types.SimpleNamespace`` fakes, matching the
convention documented in ``parsing.py`` (real Massive models need no network).
"""

import datetime as dt
from types import SimpleNamespace

from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from trade_system_massive.parsing import parse_date_to_start_ns
from trade_system_massive.parsing import parse_futures_bar
from trade_system_massive.parsing import parse_futures_quote_tick
from trade_system_massive.parsing import parse_futures_snapshot_to_quote
from trade_system_massive.parsing import parse_futures_trade_tick


def _iid() -> InstrumentId:
    return InstrumentId(Symbol("ESZ4"), Venue("XCME"))


# --- parse_date_to_start_ns -----------------------------------------------------------


def test_parse_date_to_start_ns_parses_iso() -> None:
    """A YYYY-MM-DD string parses to 00:00 UTC nanoseconds."""
    expected = int(dt.datetime(2025, 12, 19, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
    assert parse_date_to_start_ns("2025-12-19") == expected


def test_parse_date_to_start_ns_zero_on_garbage() -> None:
    """An unparseable value returns 0 (not raises)."""
    assert parse_date_to_start_ns("not-a-date") == 0
    assert parse_date_to_start_ns(None) == 0
    assert parse_date_to_start_ns("") == 0


# --- parse_futures_trade_tick ---------------------------------------------------------


def test_parse_futures_trade_tick_uses_nanosecond_timestamp() -> None:
    """A futures trade's single nanosecond `timestamp` is used for ts_event/init."""
    trade = SimpleNamespace(timestamp=1_700_000_000_000_000_000, size=3, price=6052.0, sequence_number=27317882)

    tick = parse_futures_trade_tick(_iid(), trade)

    assert tick.instrument_id == _iid()
    assert tick.ts_event == 1_700_000_000_000_000_000
    assert tick.ts_init == 1_700_000_000_000_000_000
    assert str(tick.price) == "6052.0"
    assert str(tick.size) == "3"
    assert str(tick.trade_id) == "27317882"


def test_parse_futures_trade_tick_falls_back_to_report_sequence() -> None:
    """When `sequence_number` is missing, `report_sequence` is used for the trade id."""
    trade = SimpleNamespace(timestamp=1, size=1, price=100.0, sequence_number=None, report_sequence=99)

    tick = parse_futures_trade_tick(_iid(), trade)

    assert str(tick.trade_id) == "99"


def test_parse_futures_trade_tick_negative_one_when_no_sequence() -> None:
    """With no sequence at all, the trade id is the sentinel "-1"."""
    trade = SimpleNamespace(timestamp=1, size=1, price=100.0, sequence_number=None, report_sequence=None)

    tick = parse_futures_trade_tick(_iid(), trade)

    assert str(tick.trade_id) == "-1"


# --- parse_futures_quote_tick ---------------------------------------------------------


def test_parse_futures_quote_tick_uses_nanosecond_timestamp() -> None:
    """A futures quote's single nanosecond `timestamp` is used for ts_event/init."""
    quote = SimpleNamespace(
        timestamp=1_700_000_000_000_000_000,
        bid_price=6051.0,
        ask_price=6052.5,
        bid_size=10,
        ask_size=5,
    )

    tick = parse_futures_quote_tick(_iid(), quote)

    assert tick.ts_event == 1_700_000_000_000_000_000
    assert str(tick.bid_price) == "6051.0"
    assert str(tick.ask_price) == "6052.5"
    assert str(tick.bid_size) == "10"
    assert str(tick.ask_size) == "5"


# --- parse_futures_bar ----------------------------------------------------------------


def _bar_agg(**overrides) -> SimpleNamespace:
    base = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000,
        "dollar_volume": 100500.0,
        "transactions": 42,
        "window_start": 1_700_000_000_000_000_000,
        "session_end_date": "2025-12-19",
        "settlement_price": 100.5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _bar_type() -> BarType:
    spec = BarSpecification(BarAggregation.MINUTE, PriceType.LAST, 1)
    return BarType(_iid(), spec)


def test_parse_futures_bar_on_open_uses_window_start() -> None:
    """With on_close=False, the bar timestamp is window_start (nanoseconds)."""
    agg = _bar_agg()

    bar = parse_futures_bar(_bar_type(), agg, "1min", on_close=False)

    assert bar.ts_event == 1_700_000_000_000_000_000
    assert str(bar.open) == "100.0"
    assert str(bar.close) == "100.5"
    assert str(bar.volume) == "1000"


def test_parse_futures_bar_on_close_advances_fixed_resolution() -> None:
    """For a fixed-duration resolution with on_close, ts advances by the duration."""
    agg = _bar_agg(window_start=1_700_000_000_000_000_000)

    bar_min = parse_futures_bar(_bar_type(), agg, "1min", on_close=True)
    assert bar_min.ts_event == 1_700_000_000_000_000_000 + 60_000_000_000

    bar_5min = parse_futures_bar(_bar_type(), agg, "5min", on_close=True)
    assert bar_5min.ts_event == 1_700_000_000_000_000_000 + 5 * 60_000_000_000


def test_parse_futures_bar_on_close_session_stays_on_open() -> None:
    """A non-fixed resolution (session) cannot be advanced; ts stays on window_start."""
    agg = _bar_agg(window_start=1_700_000_000_000_000_000)

    bar = parse_futures_bar(_bar_type(), agg, "1session", on_close=True)

    assert bar.ts_event == 1_700_000_000_000_000_000


# --- parse_futures_snapshot_to_quote --------------------------------------------------


def test_parse_futures_snapshot_to_quote_reads_last_quote() -> None:
    """The snapshot's `last_quote` (bid/ask/bid_size/ask_size/last_updated) maps to a QuoteTick."""
    snapshot = SimpleNamespace(
        ticker="ESZ4",
        last_quote=SimpleNamespace(
            bid=6051.0,
            ask=6052.5,
            bid_size=10,
            ask_size=5,
            last_updated=1_700_000_000_000_000_000,
        ),
    )

    quote = parse_futures_snapshot_to_quote(_iid(), snapshot)

    assert quote is not None
    assert quote.ts_event == 1_700_000_000_000_000_000
    assert str(quote.bid_price) == "6051.0"
    assert str(quote.ask_price) == "6052.5"
    assert str(quote.bid_size) == "10"
    assert str(quote.ask_size) == "5"


def test_parse_futures_snapshot_to_quote_none_without_last_quote() -> None:
    """A snapshot with no `last_quote` yields None."""
    snapshot = SimpleNamespace(ticker="ESZ4", last_quote=None)

    assert parse_futures_snapshot_to_quote(_iid(), snapshot) is None
