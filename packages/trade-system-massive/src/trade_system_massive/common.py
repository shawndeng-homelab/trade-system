"""Shared helpers for the Massive.com data adapter."""

import datetime as dt
from decimal import Decimal
from typing import Any
from typing import Final

from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Venue

from trade_system_massive.constants import DEFAULT_FUTURES_VENUE
from trade_system_massive.constants import OPTION_TICKER_PREFIX
from trade_system_massive.constants import OPTION_VENUE


# Massive/Polygon time unit strings accepted by `RESTClient.list_aggs`.
TIMESPAN_SECOND: Final[str] = "second"
TIMESPAN_MINUTE: Final[str] = "minute"
TIMESPAN_HOUR: Final[str] = "hour"
TIMESPAN_DAY: Final[str] = "day"

# Nautilus caps `Price`/`Quantity` precision at 9 fractional digits.
_NAUTILUS_MAX_PRECISION: int = 9
_QUANT_9DP: Decimal = Decimal("1e-9")


def is_option_ticker(ticker: str) -> bool:
    """Return whether `ticker` is a Massive option contract ticker (``O:`` prefix)."""
    return ticker.startswith(OPTION_TICKER_PREFIX)


def is_future_ticker(ticker: str, futures_product_codes: set[str] | None) -> bool:
    """Return whether `ticker` is a Massive futures contract.

    Massive futures tickers are bare (e.g. ``ESZ4``) with no prefix, so they cannot
    be distinguished from stock tickers by string alone. Dispatch is therefore
    config-driven: a ticker is a future iff it starts with one of the configured
    ``futures_product_codes`` (e.g. ``ES`` matches ``ESZ4``, ``CL`` matches
    ``CLZ25``). Product codes are matched longest-first so a 2-letter code (``CL``)
    doesn't shadow a longer one. Returns ``False`` when the set is empty/None.

    Note: the product code cannot be *extracted* from the ticker (the month code is
    also a letter, so ``ESZ4`` could split as ``ES``/``Z``/``4`` or ``ESZ``/``4``);
    only a prefix match against known codes is reliable.

    """
    if not futures_product_codes:
        return False
    return any(ticker.startswith(code) for code in futures_product_codes)


def clamp_to_9dp(value: Any) -> str:
    """Return ``value`` as a decimal string clamped to Nautilus's 9-digit precision.

    Massive numerics are floats and may carry >9 fractional digits (e.g. a noisy
    ``12345.0000000001``), which ``Price.from_str`` / ``Quantity.from_str`` reject.
    Route through ``Decimal`` and quantize to 9 dp only when the input exceeds it,
    so normal integer/short-decimal inputs pass through unchanged.

    """
    dec = Decimal(str(value))
    if dec.as_tuple().exponent < -_NAUTILUS_MAX_PRECISION:
        dec = dec.quantize(_QUANT_9DP)
    return str(dec)


def clamp_volume(value: Any) -> str:
    """Return ``value`` as an integer string for Nautilus ``Quantity``.

    Massive API returns volumes as either ``int`` or ``float`` (e.g. ``74814505.0``).
    Using ``Quantity.from_str("74814505.0")`` creates a quantity with precision=1,
    but instruments typically have ``size_precision=0`` (integer shares/contracts).
    This function strips the fractional part to produce a precision-0 string.

    """
    dec = Decimal(str(value))
    # Clamp to 9dp if needed (same as clamp_to_9dp)
    if dec.as_tuple().exponent < -_NAUTILUS_MAX_PRECISION:
        dec = dec.quantize(_QUANT_9DP)
    # Normalize to remove trailing zeros: 74814505.0 → 74814505
    return str(dec.normalize()) if dec == dec.to_integral_value() else str(dec)


def instrument_id_to_ticker(instrument_id: InstrumentId) -> str:
    """Return the Massive ticker string for a Nautilus instrument id.

    The Nautilus symbol already carries the Massive ticker form (e.g. ``AAPL``
    for equities or ``O:AAPL251219C00150000`` for options), since the provider
    builds instrument ids directly from Massive tickers.

    """
    return instrument_id.symbol.value


def ticker_to_venue(
    ticker: str,
    equity_exchange: str | None = None,
    futures_venue: str | None = None,
    is_future: bool = False,
) -> Venue:
    """Return the Nautilus venue for a Massive ticker.

    Options route through OPRA. Futures use the contract's ``trading_venue`` MIC
    (e.g. ``XCBT``) when known, falling back to ``DEFAULT_FUTURES_VENUE``. Equities
    use the symbol's primary exchange (e.g. ``XNAS``) when known, falling back to
    ``XNAS``.

    """
    if is_option_ticker(ticker):
        return Venue(OPTION_VENUE)
    if is_future:
        return Venue(futures_venue or DEFAULT_FUTURES_VENUE)
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


# --------------------------------------------------------------------------- futures

# Massive futures aggregate `resolution` units (number+unit string, e.g. "5min").
FUTURES_RESOLUTION_SECOND: Final[str] = "sec"
FUTURES_RESOLUTION_MINUTE: Final[str] = "min"
FUTURES_RESOLUTION_HOUR: Final[str] = "hour"
FUTURES_RESOLUTION_SESSION: Final[str] = "session"

# Fixed-duration resolution units → nanoseconds. Session/week/month/quarter/year
# are NOT fixed-duration (their length varies), so they are absent here; the bar
# parser cannot advance them to a close timestamp and falls back to the open.
_FUTURES_RESOLUTION_NS: Final[dict[str, int]] = {
    FUTURES_RESOLUTION_SECOND: 1_000_000_000,
    FUTURES_RESOLUTION_MINUTE: 60_000_000_000,
    FUTURES_RESOLUTION_HOUR: 3_600_000_000_000,
}


def _resolution_split(resolution: str) -> tuple[int, str]:
    """Split a Massive futures resolution string into ``(multiplier, unit)``.

    ``"5min"``→``(5, "min")``, ``"1session"``→``(1, "session")``. A bare unit like
    ``"session"`` is treated as multiplier 1.

    """
    digits = ""
    i = 0
    while i < len(resolution) and resolution[i].isdigit():
        digits += resolution[i]
        i += 1
    n = int(digits) if digits else 1
    return n, resolution[i:]


def resolution_is_fixed_duration(resolution: str) -> bool:
    """Return whether `resolution` has a fixed, computable duration (sec/min/hour)."""
    _, unit = _resolution_split(resolution)
    return unit in _FUTURES_RESOLUTION_NS


def resolution_duration_ns(resolution: str) -> int:
    """Return the duration of a fixed-resolution bar in nanoseconds.

    Returns ``0`` for non-fixed resolutions (session/week/month/...), for which the
    close timestamp cannot be computed from the open alone.

    """
    n, unit = _resolution_split(resolution)
    unit_ns = _FUTURES_RESOLUTION_NS.get(unit, 0)
    return n * unit_ns if unit_ns else 0


def bar_type_to_futures_resolution(bar_type: BarType) -> str:
    """Map a Nautilus externally-aggregated time bar to a Massive futures resolution.

    Massive futures aggregates use a single ``resolution`` string (e.g. ``"1sec"``,
    ``"5min"``) rather than the stock ``(multiplier, timespan)`` pair. Nautilus
    ``BarAggregation.DAY`` maps to ``"1session"`` (the closest futures equivalent —
    Massive has no ``day`` unit; a futures "day" is one trading session).

    Raises:
    ------
    ValueError
        If `bar_type` cannot be mapped to a Massive futures resolution.

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
            return f"{spec.step}{FUTURES_RESOLUTION_SECOND}"
        case BarAggregation.MINUTE:
            return f"{spec.step}{FUTURES_RESOLUTION_MINUTE}"
        case BarAggregation.HOUR:
            return f"{spec.step}{FUTURES_RESOLUTION_HOUR}"
        case BarAggregation.DAY:
            return f"{spec.step}{FUTURES_RESOLUTION_SESSION}"
        case _:
            raise ValueError(
                f"bar type '{bar_type}' uses unsupported aggregation {spec.aggregation}; use SECOND/MINUTE/HOUR/DAY",
            )


def futures_time_range_params(request) -> dict:
    """Map a request's ns start/end to futures ``timestamp_gte``/``timestamp_lte``.

    Unlike stock trades/quotes (whose ``timestamp_gte``/``timestamp_lte`` take
    millisecond integers), the futures trades/quotes endpoints accept nanosecond
    integers, so no conversion is applied. When only one bound is set, only that
    bound is passed.

    """
    params: dict = {}
    if request.start is not None:
        params["timestamp_gte"] = int(request.start)
    if request.end is not None:
        params["timestamp_lte"] = int(request.end)
    return params
