"""Data loading conveniences backed by optopsy's parquet cache.

Wraps ``optopsy.load_cached_options`` and ``optopsy.load_cached_stocks``
so strategy code has a single import path for data access.

Data must be pre-downloaded via the ``optopsy-data`` CLI::

    EODHD_API_KEY=... optopsy-data download SPY        # options
    optopsy-data download SPY -s                       # stock OHLCV
"""

import optopsy as op


def load_pmcc_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    expiration_type: str = "monthly",
) -> tuple:
    """Load option chain and stock data for PMCC backtesting.

    Args:
        symbol: Ticker symbol (e.g. "SPY").
        start_date: Optional start date (YYYY-MM-DD).
        end_date: Optional end date (YYYY-MM-DD).
        expiration_type: "monthly" or "weekly".

    Returns:
        (options_df, stock_df) tuple.

    Raises:
        FileNotFoundError: If no cached data exists for *symbol*.
    """
    options = op.load_cached_options(symbol, start_date, end_date)

    # Filter by expiration type if the column exists
    if expiration_type and "expiration_type" in options.columns:
        options = options[options["expiration_type"].str.lower() == expiration_type.lower()].copy()

    stock = op.load_cached_stocks(symbol, start_date, end_date)
    return options, stock
