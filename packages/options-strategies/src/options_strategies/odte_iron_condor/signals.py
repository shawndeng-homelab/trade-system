"""Iron condor entry-date signal generators.

Produces ``(underlying_symbol, quote_date)`` DataFrames for use as
``entry_dates`` in optopsy strategy functions.

Entry frequency is controlled by the ``entry_cycle`` parameter:

- ``"daily"`` — every trading day (0DTE / near-expiry style)
- ``"weekly"`` — first trading day of each ISO week
- ``"biweekly"`` — first trading day of every other ISO week
- ``"monthly"`` — first trading day of each calendar month

The ``entry_time`` parameter is informational — intraday time filtering
requires intraday bar data, which is not available in the daily-frequency
EODHD dataset.
"""

import pandas as pd


def odte_entry_dates(
    stock: pd.DataFrame,
    *,
    entry_cycle: str = "daily",
    entry_time: str = "15:30",
) -> pd.DataFrame:
    """Generate entry dates for iron condor from stock data.

    Args:
        stock: OHLCV DataFrame from ``load_cached_stocks``.
        entry_cycle: How often to open new positions.  One of "daily",
            "weekly", "biweekly", "monthly".
        entry_time: Target entry time as HH:MM string.  Informational
            only with daily data; reserved for future intraday support.

    Returns:
        DataFrame with columns (underlying_symbol, quote_date).

    Raises:
        ValueError: If *entry_cycle* is not a recognised value.
    """
    df = stock.copy()
    df["quote_date"] = pd.to_datetime(df["quote_date"])
    df = df.sort_values(["underlying_symbol", "quote_date"])

    if entry_cycle == "daily":
        # Every trading day is a valid entry
        unique = df.drop_duplicates(subset=["underlying_symbol", "quote_date"])

    elif entry_cycle == "weekly":
        # First trading day of each ISO week
        df["_yr"] = df["quote_date"].dt.isocalendar().year.astype(int)
        df["_wk"] = df["quote_date"].dt.isocalendar().week.astype(int)
        unique = df.groupby(["underlying_symbol", "_yr", "_wk"]).first().reset_index()

    elif entry_cycle == "biweekly":
        # First trading day of every other ISO week (even week numbers)
        df["_yr"] = df["quote_date"].dt.isocalendar().year.astype(int)
        df["_wk"] = df["quote_date"].dt.isocalendar().week.astype(int)
        df["_biwk"] = df["_wk"] // 2
        unique = df.groupby(["underlying_symbol", "_yr", "_biwk"]).first().reset_index()

    elif entry_cycle == "monthly":
        # First trading day of each calendar month
        df["_ym"] = df["quote_date"].dt.to_period("M")
        unique = df.groupby(["underlying_symbol", "_ym"]).first().reset_index()

    else:
        msg = f"Unknown entry_cycle: {entry_cycle!r}. Use 'daily', 'weekly', 'biweekly', or 'monthly'."
        raise ValueError(msg)

    return unique[["underlying_symbol", "quote_date"]].reset_index(drop=True)
