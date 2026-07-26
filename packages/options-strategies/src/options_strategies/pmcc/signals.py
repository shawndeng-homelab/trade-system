"""PMCC entry-date signal generators.

Produces ``(underlying_symbol, quote_date)`` DataFrames for each leg
independently, suitable for passing as ``entry_dates`` to optopsy
strategy functions.

Uses optopsy's built-in signal library (iv_rank, rsi, day_of_week, etc.)
with ``signal_dates()`` to compute valid entry dates from stock OHLCV data.
"""

import optopsy as op
import pandas as pd


def leaps_entry_dates(
    stock: pd.DataFrame,
    *,
    method: str = "monthly_start",
) -> pd.DataFrame:
    """Generate LEAPS entry dates from stock data.

    LEAPS are long-duration positions; entry frequency is low (e.g. monthly).

    Args:
        stock: OHLCV DataFrame from ``load_cached_stocks``.
        method: Signal method. Currently supported:
            - "monthly_start": Enter on the first trading day of each month.

    Returns:
        DataFrame with columns (underlying_symbol, quote_date).
    """
    if method == "monthly_start":
        # First trading day of each month: use day_of_week + monthly logic.
        # Simple approach: mark the first bar of each month.
        df = stock.copy()
        df["quote_date"] = pd.to_datetime(df["quote_date"])
        df = df.sort_values(["underlying_symbol", "quote_date"])
        df["_ym"] = df["quote_date"].dt.to_period("M")
        first_of_month = df.groupby(["underlying_symbol", "_ym"]).first().reset_index()
        return first_of_month[["underlying_symbol", "quote_date"]].reset_index(drop=True)

    # Future: support iv_rank_above, etc.
    msg = f"Unknown LEAPS entry method: {method!r}"
    raise ValueError(msg)


def short_call_entry_dates(
    stock: pd.DataFrame,
    *,
    method: str = "weekly_start",
) -> pd.DataFrame:
    """Generate short call entry dates from stock data.

    Short calls rotate more frequently than LEAPS; entry is weekly or
    signal-driven.

    Args:
        stock: OHLCV DataFrame from ``load_cached_stocks``.
        method: Signal method. Currently supported:
            - "weekly_start": Enter on the first trading day of each week.
            - "iv_rank_above": Enter when IV rank is above a threshold.

    Returns:
        DataFrame with columns (underlying_symbol, quote_date).
    """
    if method == "weekly_start":
        df = stock.copy()
        df["quote_date"] = pd.to_datetime(df["quote_date"])
        df = df.sort_values(["underlying_symbol", "quote_date"])
        df["_yw"] = df["quote_date"].dt.isocalendar().week.astype(int)
        df["_yr"] = df["quote_date"].dt.year
        first_of_week = df.groupby(["underlying_symbol", "_yr", "_yw"]).first().reset_index()
        return first_of_week[["underlying_symbol", "quote_date"]].reset_index(drop=True)

    if method == "iv_rank_above":
        # Use optopsy's built-in IV rank signal
        sig = op.signal(op.iv_rank_above(50))
        return op.signal_dates(stock, sig)

    msg = f"Unknown short call entry method: {method!r}"
    raise ValueError(msg)
