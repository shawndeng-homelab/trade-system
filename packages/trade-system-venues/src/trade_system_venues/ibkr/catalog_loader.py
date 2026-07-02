"""Download IBKR historical data into a fixed ``ParquetDataCatalog`` for backtests.

This wraps NautilusTrader's ``HistoricInteractiveBrokersClient`` so downloaded stock/ETF
bars and option-chain instruments land in a single, reusable catalog (the "fixed
location"). Point every backtest at the same catalog and slice by instrument + time.

Requirements (runtime only):

- A running **TWS** or **IB Gateway** the client can connect to.
- Appropriate IBKR market-data permissions for the instruments requested.

Fixed location: by default the catalog is resolved from ``ParquetDataCatalog.from_env()``
(the ``NAUTILUS_PATH`` environment variable → ``$NAUTILUS_PATH/catalog``). Set
``NAUTILUS_PATH`` once and both download and backtest scripts share the same store.

Example:
-------
```python
import asyncio
import datetime as dt
from trade_system_venues.ibkr import catalog_loader as cl

async def main() -> None:
    catalog = cl.default_catalog()
    client = await cl.make_client(host="127.0.0.1", port=7497, client_id=5)
    await cl.download_stock_bars(
        client, catalog,
        instrument_ids=["AAPL.NASDAQ", "SPY.ARCA"],
        bar_specifications=["1-DAY-LAST", "1-HOUR-LAST"],
        start=dt.datetime(2024, 1, 1), end=dt.datetime(2024, 6, 30),
    )
    await cl.download_option_chain(client, catalog, underlying="SPY", primary_exchange="ARCA")

asyncio.run(main())
```
"""



import datetime as dt

from ibapi.common import MarketDataTypeEnum
from nautilus_trader.adapters.interactive_brokers.common import IBContract
from nautilus_trader.adapters.interactive_brokers.historical.client import HistoricInteractiveBrokersClient
from nautilus_trader.persistence.catalog import ParquetDataCatalog


# IBKR options settle in the US on regular trading hours; default the download tz.
DEFAULT_TZ = "America/New_York"


def default_catalog() -> ParquetDataCatalog:
    """Return the shared catalog resolved from the ``NAUTILUS_PATH`` environment variable.

    Returns:
        The catalog rooted at ``$NAUTILUS_PATH/catalog``.

    """
    return ParquetDataCatalog.from_env()


async def make_client(
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 5,
    delayed_data: bool = True,
    log_level: str = "INFO",
) -> HistoricInteractiveBrokersClient:
    """Create and connect a ``HistoricInteractiveBrokersClient``.

    Args:
        host: TWS/Gateway host.
        port: TWS/Gateway port (7497 paper TWS, 7496 live TWS, 4001/4002 gateway).
        client_id: IB API client id (must be unique per concurrent connection).
        delayed_data: Use ``DELAYED_FROZEN`` market data (sufficient for backtests and
            avoids needing live subscriptions); set ``False`` for real-time.
        log_level: Client log level.

    Returns:
        A connected ``HistoricInteractiveBrokersClient``.

    """
    market_data_type = MarketDataTypeEnum.DELAYED_FROZEN if delayed_data else MarketDataTypeEnum.REALTIME
    client = HistoricInteractiveBrokersClient(
        host=host,
        port=port,
        client_id=client_id,
        market_data_type=market_data_type,
        log_level=log_level,
    )
    await client.connect()
    return client


async def download_stock_bars(
    client: HistoricInteractiveBrokersClient,
    catalog: ParquetDataCatalog,
    *,
    instrument_ids: list[str],
    bar_specifications: list[str],
    start: dt.datetime,
    end: dt.datetime,
    tz_name: str = DEFAULT_TZ,
    use_rth: bool = True,
    timeout: int = 120,
) -> None:
    """Download stock/ETF instruments and bars, writing both to the catalog.

    Args:
        client: A connected ``HistoricInteractiveBrokersClient``.
        catalog: The destination catalog.
        instrument_ids: Instrument IDs such as ``"AAPL.NASDAQ"`` / ``"SPY.ARCA"``.
        bar_specifications: Bar specs such as ``["1-DAY-LAST", "1-HOUR-LAST"]``.
        start: Start datetime (interpreted in ``tz_name``).
        end: End datetime (interpreted in ``tz_name``).
        tz_name: Timezone for the request window.
        use_rth: Restrict to regular trading hours.
        timeout: Per-request timeout in seconds.

    """
    instruments = await client.request_instruments(instrument_ids=instrument_ids)
    catalog.write_data(instruments)

    bars = await client.request_bars(
        bar_specifications=bar_specifications,
        start_date_time=start,
        end_date_time=end,
        tz_name=tz_name,
        instrument_ids=instrument_ids,
        use_rth=use_rth,
        timeout=timeout,
    )
    catalog.write_data(bars)


async def download_option_chain(
    client: HistoricInteractiveBrokersClient,
    catalog: ParquetDataCatalog,
    *,
    underlying: str,
    primary_exchange: str,
    exchange: str = "SMART",
    min_expiry_days: int = 7,
    max_expiry_days: int = 30,
) -> None:
    """Download an option chain's instrument definitions and write them to the catalog.

    Only instrument definitions are fetched here — historical option bars/ticks are
    requested separately (and are often sparse; see the IBKR data caveats).

    Args:
        client: A connected ``HistoricInteractiveBrokersClient``.
        catalog: The destination catalog.
        underlying: Underlying symbol, e.g. ``"SPY"``.
        primary_exchange: Primary listing exchange of the underlying, e.g. ``"ARCA"``.
        exchange: Routing exchange (usually ``"SMART"``).
        min_expiry_days: Earliest expiry (days from now) to include.
        max_expiry_days: Latest expiry (days from now) to include.

    """
    chain_contract = IBContract(
        secType="STK",
        symbol=underlying,
        exchange=exchange,
        primaryExchange=primary_exchange,
        build_options_chain=True,
        min_expiry_days=min_expiry_days,
        max_expiry_days=max_expiry_days,
    )
    instruments = await client.request_instruments(contracts=[chain_contract])
    catalog.write_data(instruments)
