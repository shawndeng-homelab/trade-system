"""Download Massive.com (Polygon-compatible) option data into a ParquetDataCatalog.

This mirrors :mod:`trade_system_venues.ibkr.catalog_loader` so that option chain
instruments and their OHLCV bars land in the shared catalog (rooted at
``$NAUTILUS_PATH/catalog``). Backtest scripts point at the same catalog and slice
by instrument + time.

Requirements (runtime only):

- A valid Massive/Polygon API key (set ``MASSIVE_API_KEY`` or ``POLYGON_API_KEY``).
- Sufficient API tier quota for the instruments requested (free tier is 5 calls/min).

Example:
-------
```python
import asyncio
import datetime as dt
from trade_system_massive import catalog_loader as cl

async def main() -> None:
    catalog = cl.default_catalog()
    client, limiter = cl.make_client()

    # Download SPY underlying bars
    await cl.download_underlying_bars(
        client, limiter, catalog,
        ticker="SPY",
        from_="2024-01-02",
        to="2024-06-30",
    )

    # Download SPY option chain instruments
    await cl.download_option_chain(client, limiter, catalog, underlying="SPY")

    # Download daily bars for each option contract
    await cl.download_option_bars(
        client, limiter, catalog,
        underlying="SPY",
        from_="2024-01-02",
        to="2024-06-30",
    )

asyncio.run(main())
```
"""

import datetime as dt
import os

from massive import RESTClient
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from trade_system_massive.common import ticker_to_venue
from trade_system_massive.constants import DEFAULT_BASE_URL
from trade_system_massive.constants import DEFAULT_BURST
from trade_system_massive.constants import DEFAULT_RATE_LIMIT_PER_MIN
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.instruments import MassiveInstrumentProviderConfig
from trade_system_massive.parsing import parse_bar
from trade_system_massive.rate_limiter import TokenBucketRateLimiter
from trade_system_massive.rate_limiter import rate_limited_call
from trade_system_massive.rate_limiter import rate_per_min_to_per_sec


def default_catalog() -> ParquetDataCatalog:
    """Return the shared catalog resolved from the ``NAUTILUS_PATH`` environment variable.

    Returns:
        The catalog rooted at ``$NAUTILUS_PATH/catalog``.

    """
    return ParquetDataCatalog.from_env()


def make_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    rate_limit_per_min: float | None = None,
    burst: int | None = None,
    trace: bool = False,
    pagination_limit: int = 50_000,
) -> tuple[RESTClient, TokenBucketRateLimiter]:
    """Create a Massive REST client and rate limiter for catalog downloads.

    Args:
        api_key: Massive API key. Falls back to ``MASSIVE_API_KEY`` / ``POLYGON_API_KEY``.
        base_url: REST base URL override. Defaults to ``https://api.massive.com``.
        rate_limit_per_min: Sustained request rate budget. Defaults to 5.
        burst: Maximum burst calls. Defaults to 5.
        trace: Whether to print request/response diagnostics.
        pagination_limit: Page size for paginated endpoints.

    Returns:
        ``(rest_client, rate_limiter)`` ready for use with the download functions.

    """
    resolved_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""
    resolved_url = base_url or DEFAULT_BASE_URL
    resolved_rate = rate_limit_per_min or DEFAULT_RATE_LIMIT_PER_MIN
    resolved_burst = burst or DEFAULT_BURST

    client = RESTClient(
        api_key=resolved_key,
        base=resolved_url,
        pagination=True,
        trace=trace,
    )
    limiter = TokenBucketRateLimiter(
        rate=rate_per_min_to_per_sec(resolved_rate),
        burst=resolved_burst,
    )
    return client, limiter


async def download_option_chain(
    client: RESTClient,
    limiter: TokenBucketRateLimiter,
    catalog: ParquetDataCatalog,
    *,
    underlying: str,
    expired: bool = False,
    pagination_limit: int = 50_000,
) -> None:
    """Download an option chain's instrument definitions and write them to the catalog.

    Pages through ``list_options_contracts`` for the underlying, parses each contract
    into a NautilusTrader :class:`OptionContract`, and writes them all to the catalog.

    Args:
        client: The Massive REST client.
        limiter: The rate limiter gating every REST call.
        catalog: The destination ParquetDataCatalog.
        underlying: Underlying equity ticker, e.g. ``"SPY"``.
        expired: Whether to include expired contracts.
        pagination_limit: Page size for the Massive API.

    """
    provider = MassiveInstrumentProvider(
        client=client,
        rate_limiter=limiter,
        clock=_FakeClock(),
        config=MassiveInstrumentProviderConfig(),
    )

    contracts_iter = await rate_limited_call(
        limiter,
        client.list_options_contracts,
        underlying_ticker=underlying,
        expired=expired,
        limit=pagination_limit,
    )

    instruments: list[OptionContract] = []
    for contract in contracts_iter:
        instrument = provider._parse_options_contract(contract)
        if instrument is not None:
            instruments.append(instrument)

    if instruments:
        catalog.write_data(instruments)

    print(f"Downloaded {len(instruments)} option contracts for {underlying}")


async def download_option_bars(
    client: RESTClient,
    limiter: TokenBucketRateLimiter,
    catalog: ParquetDataCatalog,
    *,
    underlying: str,
    multiplier: int = 1,
    timespan: str = "day",
    from_: str | None = None,
    to: str | None = None,
    min_dte: int = 0,
    max_dte: int | None = None,
    max_contracts: int | None = None,
) -> None:
    """Download OHLCV bars for option contracts and write them to the catalog.

    For each option contract already in the catalog for the given underlying,
    fetches daily (or other resolution) bars and writes them.

    Args:
        client: The Massive REST client.
        limiter: The rate limiter gating every REST call.
        catalog: The destination ParquetDataCatalog.
        underlying: Underlying equity ticker, e.g. ``"SPY"``.
        multiplier: Bar multiplier (e.g. 1 for 1-day).
        timespan: Bar timespan (``"minute"``, ``"hour"``, ``"day"``).
        from_: Start date string (``"YYYY-MM-DD"``).
        to: End date string (``"YYYY-MM-DD"``).
        min_dte: Skip contracts with DTE below this at download time.
        max_dte: Skip contracts with DTE above this at download time.
        max_contracts: Maximum number of contracts to download bars for (``None`` = all).

    """
    # Load option instruments from catalog
    all_instruments = catalog.instruments()
    option_instruments = [
        inst for inst in all_instruments if isinstance(inst, OptionContract) and inst.underlying == underlying
    ]

    # Filter by DTE
    now = dt.datetime.now(tz=dt.UTC)
    filtered: list[OptionContract] = []
    for inst in option_instruments:
        expiry = dt.datetime.fromtimestamp(inst.expiration_ns / 1e9, tz=dt.UTC)
        dte = (expiry.date() - now.date()).days
        if dte < min_dte:
            continue
        if max_dte is not None and dte > max_dte:
            continue
        filtered.append(inst)

    if max_contracts is not None:
        filtered = filtered[:max_contracts]

    total_bars = 0
    for inst in filtered:
        ticker = inst.id.symbol.value
        bar_type = BarType.from_str(
            f"{inst.id}-{multiplier}-{timespan.upper()}-LAST-EXTERNAL",
        )
        try:
            aggs = await rate_limited_call(
                limiter,
                client.list_aggs,
                ticker,
                multiplier,
                timespan,
                from_ or "",
                to or "",
                limit=50_000,
            )
            bars = [parse_bar(bar_type, agg, multiplier, timespan, True) for agg in aggs]
            if bars:
                catalog.write_data(bars)
                total_bars += len(bars)
        except Exception as exc:
            print(f"  Skipping {ticker}: {exc}")
            continue

    print(f"Downloaded {total_bars} option bars across {len(filtered)} contracts for {underlying}")


async def download_underlying_bars(
    client: RESTClient,
    limiter: TokenBucketRateLimiter,
    catalog: ParquetDataCatalog,
    *,
    ticker: str,
    multiplier: int = 1,
    timespan: str = "hour",
    from_: str | None = None,
    to: str | None = None,
) -> None:
    """Download underlying equity OHLCV bars and write them to the catalog.

    Args:
        client: The Massive REST client.
        limiter: The rate limiter gating every REST call.
        catalog: The destination ParquetDataCatalog.
        ticker: Equity ticker, e.g. ``"SPY"``.
        multiplier: Bar multiplier.
        timespan: Bar timespan.
        from_: Start date string.
        to: End date string.

    """
    venue = ticker_to_venue(ticker)
    instrument_id = InstrumentId(Symbol(ticker), venue)
    bar_type = BarType.from_str(
        f"{instrument_id}-{multiplier}-{timespan.upper()}-LAST-EXTERNAL",
    )
    aggs = await rate_limited_call(
        limiter,
        client.list_aggs,
        ticker,
        multiplier,
        timespan,
        from_ or "",
        to or "",
        limit=50_000,
    )
    bars = [parse_bar(bar_type, agg, multiplier, timespan, True) for agg in aggs]
    if bars:
        catalog.write_data(bars)

    print(f"Downloaded {len(bars)} {multiplier}-{timespan} bars for {ticker}")


class _FakeClock:
    """A clock stub returning a fixed nanosecond timestamp for catalog downloads."""

    def __init__(self, ts_ns: int = 1_700_000_000_000_000_000) -> None:
        self._ts = ts_ns

    def timestamp_ns(self) -> int:
        return self._ts
