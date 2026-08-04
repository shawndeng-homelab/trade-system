"""Data loading conveniences backed by optopsy's parquet cache.

Wraps ``optopsy.load_cached_options`` and ``optopsy.load_cached_stocks``
so strategy code has a single import path for data access.

Data must be pre-downloaded via the ``optopsy-data`` CLI::

    EODHD_API_KEY=... optopsy-data download SPY        # options
    optopsy-data download SPY -s                       # stock OHLCV
"""

from datetime import date as date_cls

import optopsy as op

from options_strategies.earnings_overnight.signals import load_earnings_calendar


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


def load_benchmark_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple:
    """Load option chain and stock data for benchmark backtesting.

    Loads the full option chain and stock OHLCV from the optopsy parquet
    cache.  The benchmark strategy uses LEAPS-range DTE (up to 730 days),
    so no expiration type filtering is applied.

    Data must be pre-downloaded via the ``optopsy-data`` CLI::

        EODHD_API_KEY=... optopsy-data download SPY        # options
        optopsy-data download SPY -s                       # stock OHLCV

    Args:
        symbol: Ticker symbol (e.g. "SPY").
        start_date: Optional start date (YYYY-MM-DD).
        end_date: Optional end date (YYYY-MM-DD).

    Returns:
        (options_df, stock_df) tuple.

    Raises:
        FileNotFoundError: If no cached data exists for *symbol*.
    """
    options = op.load_cached_options(symbol, start_date, end_date)
    stock = op.load_cached_stocks(symbol, start_date, end_date)
    return options, stock


def load_odte_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple:
    """Load 0DTE option chain and stock data for iron condor backtesting.

    Loads the full option chain and stock OHLCV from the optopsy parquet
    cache.  0DTE filtering is handled by optopsy's ``max_entry_dte`` and
    ``exit_dte`` strategy parameters rather than pre-filtering the data,
    so that optopsy can correctly compute DTE internally.

    Data must be pre-downloaded via the ``optopsy-data`` CLI::

        EODHD_API_KEY=... optopsy-data download SPY        # options
        optopsy-data download SPY -s                       # stock OHLCV

    Args:
        symbol: Ticker symbol (e.g. "SPY").
        start_date: Optional start date (YYYY-MM-DD).
        end_date: Optional end date (YYYY-MM-DD).

    Returns:
        (options_df, stock_df) tuple.

    Raises:
        FileNotFoundError: If no cached data exists for *symbol*.
    """
    options = op.load_cached_options(symbol, start_date, end_date)
    stock = op.load_cached_stocks(symbol, start_date, end_date)
    return options, stock


def load_earnings_overnight_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    as_of_date: date_cls | None = None,
) -> tuple:
    """Load options, stock, and earnings calendar for the earnings-overnight strategy.

    The earnings cache lives at ``$OPTOPSY_DATA_DIR/cache/earnings/`` and
    is populated by the ``earnings-data`` CLI::

        earnings-data download --symbols SPY

    Args:
        symbol: Ticker symbol (e.g. "SPY"). Normalized to vendor-native
            form (e.g. "SPY.US") before reading the cache.
        start_date: Optional start date (YYYY-MM-DD) for options/stock.
        end_date: Optional end date (YYYY-MM-DD) for options/stock.
        as_of_date: Optional backtest cutoff; events with ``report_date``
            after this are filtered out (prevents peeking at EODHD's
            pre-published future events). Pass ``date.today()`` for a
            point-in-time backtest.

    Returns:
        ``(options_df, stock_df, earnings_calendar)`` tuple. The
        ``earnings_calendar`` is a ``{code: [report_dates]}`` dict that
        can be passed directly to :func:`run_earnings_overnight`.
    """
    options = op.load_cached_options(symbol, start_date, end_date)
    stock = op.load_cached_stocks(symbol, start_date, end_date)
    earnings = load_earnings_calendar([symbol], as_of_date=as_of_date)
    return options, stock, earnings
