"""Benchmark entry-date signal generators.

Produces ``(underlying_symbol, quote_date)`` DataFrames for use as
``entry_dates`` in optopsy strategy functions.

For the rolling ATM call benchmark, every trading day is a valid entry
date.  With ``max_positions=1``, optopsy will enter on the first
available date, exit when DTE hits ``exit_dte``, and immediately re-enter
on the next trading day -- producing continuous rolling exposure.
"""

import pandas as pd


def benchmark_entry_dates(stock: pd.DataFrame) -> pd.DataFrame:
    """Generate entry dates for the rolling ATM call benchmark.

    Every trading day is a valid entry date.  The rolling behavior is
    achieved by combining all-trading-day entry dates with
    ``max_positions=1`` and ``exit_dte=150``: optopsy enters on the
    first available date, exits when DTE drops to 150, and re-enters
    on the very next trading day.

    Args:
        stock: OHLCV DataFrame from ``load_cached_stocks``.

    Returns:
        DataFrame with columns (underlying_symbol, quote_date).
    """
    df = stock.copy()
    df["quote_date"] = pd.to_datetime(df["quote_date"])
    df = df.sort_values(["underlying_symbol", "quote_date"])
    unique = df.drop_duplicates(subset=["underlying_symbol", "quote_date"])
    return unique[["underlying_symbol", "quote_date"]].reset_index(drop=True)
