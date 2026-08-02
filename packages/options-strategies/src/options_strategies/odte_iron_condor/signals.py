"""0DTE iron condor entry-date signal generators.

Produces ``(underlying_symbol, quote_date)`` DataFrames for use as
``entry_dates`` in optopsy strategy functions.

For 0DTE strategies, every trading day is a potential entry day since
0DTE options expire the same session.  The ``entry_time`` parameter is
informational — intraday time filtering requires intraday bar data,
which is not available in the daily-frequency EODHD dataset.
"""

import pandas as pd


def odte_entry_dates(
    stock: pd.DataFrame,
    *,
    entry_time: str = "15:30",
) -> pd.DataFrame:
    """Generate entry dates for 0DTE iron condor from stock data.

    Every trading day is a valid entry for 0DTE strategies.  The
    ``entry_time`` parameter documents the intended real-world entry
    window (e.g. 15:30 = 30 minutes before close) but is not used for
    filtering with daily-frequency data.

    Args:
        stock: OHLCV DataFrame from ``load_cached_stocks``.
        entry_time: Target entry time as HH:MM string.  Informational
            only with daily data; reserved for future intraday support.

    Returns:
        DataFrame with columns (underlying_symbol, quote_date), one row
        per trading day per symbol.
    """
    df = stock.copy()
    df["quote_date"] = pd.to_datetime(df["quote_date"])
    df = df.sort_values(["underlying_symbol", "quote_date"])
    # Deduplicate: one entry per (symbol, date)
    unique = df.drop_duplicates(subset=["underlying_symbol", "quote_date"])
    return unique[["underlying_symbol", "quote_date"]].reset_index(drop=True)
