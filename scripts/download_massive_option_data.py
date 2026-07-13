"""Download option data from Massive.com (Polygon-compatible) into the shared catalog.

Writes option chain instruments and OHLCV bars to the ParquetDataCatalog rooted at
``$NAUTILUS_PATH/catalog``, so backtest scripts can read them directly.

Run:
    uv run --all-packages python scripts/download_massive_option_data.py
"""

import asyncio

from trade_system_massive.catalog_loader import default_catalog
from trade_system_massive.catalog_loader import download_option_bars
from trade_system_massive.catalog_loader import download_option_chain
from trade_system_massive.catalog_loader import download_underlying_bars
from trade_system_massive.catalog_loader import make_client


async def main() -> None:
    """Download SPY underlying bars + option chain + option bars from Massive."""
    catalog = default_catalog()
    client, limiter = make_client()

    underlying = "SPY"
    from_ = "2024-01-02"
    to = "2024-12-31"

    # 1. Download underlying hourly bars
    await download_underlying_bars(
        client,
        limiter,
        catalog,
        ticker=underlying,
        multiplier=1,
        timespan="hour",
        from_=from_,
        to=to,
    )

    # 2. Download option chain instruments (all strikes, non-expired)
    await download_option_chain(
        client,
        limiter,
        catalog,
        underlying=underlying,
        expired=False,
    )

    # 3. Download daily bars for each option contract
    await download_option_bars(
        client,
        limiter,
        catalog,
        underlying=underlying,
        multiplier=1,
        timespan="day",
        from_=from_,
        to=to,
        min_dte=1,
        max_dte=365,
    )

    print(f"\nDone. Catalog at: {catalog.path}")


if __name__ == "__main__":
    asyncio.run(main())
