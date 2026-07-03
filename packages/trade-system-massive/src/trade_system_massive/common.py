"""Shared helpers for the Massive.com data adapter."""

import datetime as dt
from typing import Final

from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Venue

from trade_system_massive.constants import OPTION_TICKER_PREFIX
from trade_system_massive.constants import OPTION_VENUE


# Massive/Polygon time unit strings accepted by `RESTClient.list_aggs`.
TIMESPAN_SECOND: Final[str] = "second"
TIMESPAN_MINUTE: Final[str] = "minute"
TIMESPAN_HOUR: Final[str] = "hour"
TIMESPAN_DAY: Final[str] = "day"


def is_option_ticker(ticker: str) -> bool:
    """Return whether `ticker` is a Massive option contract ticker (``O:`` prefix)."""
    return ticker.startswith(OPTION_TICKER_PREFIX)


def instrument_id_to_ticker(instrument_id: InstrumentId) -> str:
    """Return the Massive ticker string for a Nautilus instrument id.

    The Nautilus symbol already carries the Massive ticker form (e.g. ``AAPL``
    for equities or ``O:AAPL251219C00150000`` for options), since the provider
    builds instrument ids directly from Massive tickers.

    """
    return instrument_id.symbol.value


def ticker_to_venue(ticker: str, equity_exchange: str | None = None) -> Venue:
    """Return the Nautilus venue for a Massive ticker.

    Options route through OPRA. Equities use the symbol's primary exchange
    (e.g. ``XNAS``) when known, falling back to ``XNAS``.

    """
    if is_option_ticker(ticker):
        return Venue(OPTION_VENUE)
    return Venue(equity_exchange or "XNAS")


def option_kind_from_contract_type(contract_type: str | None) -> OptionKind:
    """Map a Massive ``contract_type`` string to a Nautilus ``OptionKind``."""
    if contract_type and contract_type.lower().startswith("p"):
        return OptionKind.PUT
    return OptionKind.CALL


def bar_type_to_aggs_params(bar_type: BarType) -> tuple[int, str]:
    """Map a Nautilus externally-aggregated time bar to ``(multiplier, timespan)``.

    Parameters
    ----------
    bar_type : BarType
        The bar type. Must be externally aggregated, time-based, with step 1.

    Returns:
    -------
    tuple[int, str]
        The ``(multiplier, timespan)`` for ``RESTClient.list_aggs``.

    Raises:
    ------
    ValueError
        If `bar_type` cannot be mapped to a Massive aggregate.

    """
    spec = bar_type.spec
    if not bar_type.is_externally_aggregated():
        raise ValueError(f"bar type '{bar_type}' is not externally aggregated")
    if not spec.is_time_aggregated():
        raise ValueError(f"bar type '{bar_type}' is not time-aggregated")
    if spec.step != 1:
        raise ValueError(f"bar type '{bar_type}' has step {spec.step}; only 1 is supported")

    match spec.aggregation:
        case BarAggregation.SECOND:
            return spec.step, TIMESPAN_SECOND
        case BarAggregation.MINUTE:
            return spec.step, TIMESPAN_MINUTE
        case BarAggregation.HOUR:
            return spec.step, TIMESPAN_HOUR
        case BarAggregation.DAY:
            return spec.step, TIMESPAN_DAY
        case _:
            raise ValueError(
                f"bar type '{bar_type}' uses unsupported aggregation {spec.aggregation}; use SECOND/MINUTE/HOUR/DAY",
            )


def date_to_str(value: dt.date | dt.datetime | str | int | None) -> str | int | None:
    """Normalize a date-ish value to the string/int Massive accepts for ``from_``/``to``."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return value


def ms_to_ns(ms: int) -> int:
    """Convert a millisecond timestamp to nanoseconds."""
    return int(ms) * 1_000_000


def ns_to_ms(ns: int) -> int:
    """Convert a nanosecond timestamp to milliseconds."""
    return int(ns) // 1_000_000


def first_nonzero(*values: int) -> int:
    """Return the first non-zero value, or 0 if all are zero/missing."""
    for v in values:
        if v:
            return int(v)
    return 0
