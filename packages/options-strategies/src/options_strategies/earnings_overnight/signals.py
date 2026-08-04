"""Earnings-overnight signal generators.

Four pure functions that produce the (symbol, date) DataFrames and the
per-event option-row pre-selection that ``strategy.py`` hands to optopsy.

Pipeline::

    earnings_calendar  = load_earnings_calendar(symbols, as_of_date)
    events             = earnings_event_dates(stock_df, earnings_calendar, config)
    selected_options   = select_options_for_events(options_df, stock_df, events, config)
    calls_df, puts_df  = split_options_by_side(selected_options)
"""

import logging
import warnings
from datetime import date as date_cls
from pathlib import Path

import pandas as pd
from earnings_datasource.providers.eodhd import EodhdEarningsProvider
from earnings_datasource.providers.store import read_earnings

from options_strategies.earnings_overnight.config import EarningsOvernightConfig


logger = logging.getLogger(__name__)


# ── 1. Calendar loader ─────────────────────────────────────────────────────


def load_earnings_calendar(
    symbols: list[str],
    as_of_date: date_cls | None = None,
    *,
    root: Path | None = None,
) -> dict[str, list[pd.Timestamp]]:
    """Read the local earnings cache for each symbol.

    Returns a mapping ``code -> [sorted report_date Timestamps]``. Missing
    cache files are silently skipped (the symbol is omitted from the
    result). The cache is keyed on vendor-native codes (e.g. ``AAPL.US``);
    we use :meth:`EodhdEarningsProvider.normalize_symbol` to canonicalize
    bare tickers before reading.

    Args:
        symbols: Bare or vendor-native tickers (e.g. ``["SPY", "AAPL"]``).
        as_of_date: Optional backtest cutoff. Earnings events whose
            ``report_date`` is **after** this date are filtered out
            (prevents peeking at EODHD's pre-published future events).
        root: Override the optopsy data root (for tests).
    """
    provider = EodhdEarningsProvider.__new__(EodhdEarningsProvider)
    # We only need the symbol-normalization helper, not a live API session.
    # Skip the parent __init__ to avoid requiring EODHD_API_KEY.

    calendar: dict[str, list[pd.Timestamp]] = {}
    for sym in symbols:
        code = provider.normalize_symbol(sym)
        df = read_earnings(code, root=root)
        if df is None or df.empty:
            continue
        # Dedupe by report_date (defensive; the cache already dedupes).
        dates = pd.to_datetime(df["report_date"]).drop_duplicates().sort_values()
        if as_of_date is not None:
            cutoff = pd.Timestamp(as_of_date)
            dates = dates[dates <= cutoff]
        if len(dates) == 0:
            continue
        calendar[code] = list(dates)
    return calendar


# ── 2. T-1 / T-0 mapping ───────────────────────────────────────────────────


def earnings_event_dates(
    stock_df: pd.DataFrame,
    earnings_calendar: dict[str, list[pd.Timestamp]],
    config: EarningsOvernightConfig,
) -> pd.DataFrame:
    """Pair each earnings report date with its T-1 (entry) and T (exit) trading day.

    Returns a DataFrame with columns
    ``[underlying_symbol, report_date, entry_date, exit_date]``.

    - ``entry_date`` is the latest ``quote_date`` strictly before
      ``report_date`` in ``stock_df`` for the same symbol. Weekends and
      market holidays are handled automatically.
    - ``exit_date`` is the earliest ``quote_date`` on or after
      ``report_date``. Saturday reports land on Monday; if Monday is a
      holiday, the next trading day.
    - Rows where ``entry_date >= exit_date`` (defensive; no overnight) or
      where either side is ``NaT`` (event outside the data range) are
      dropped.
    """
    rows: list[dict] = []
    # Build a per-symbol sorted DatetimeIndex of trading days for O(log n)
    # lookups via ``searchsorted``.
    per_symbol_dates: dict[str, pd.DatetimeIndex] = {
        sym: pd.DatetimeIndex(group["quote_date"].drop_duplicates().sort_values())
        for sym, group in stock_df.groupby("underlying_symbol", sort=False)
    }

    for code, dates in earnings_calendar.items():
        trading_days = per_symbol_dates.get(code)
        if trading_days is None or len(trading_days) == 0:
            continue
        for report_date in dates:
            # entry: strictly before report_date
            entry_pos = trading_days.searchsorted(report_date, side="left")
            entry_date = trading_days[entry_pos - 1] if entry_pos > 0 else pd.NaT
            # exit: on or after report_date
            exit_pos = trading_days.searchsorted(report_date, side="left")
            exit_date = trading_days[exit_pos] if exit_pos < len(trading_days) else pd.NaT

            if pd.isna(entry_date) or pd.isna(exit_date):
                continue
            if entry_date >= exit_date:
                # Defensive: no overnight span (shouldn't happen in practice).
                continue
            rows.append(
                {
                    "underlying_symbol": code,
                    "report_date": pd.Timestamp(report_date),
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                }
            )

    return pd.DataFrame(rows, columns=["underlying_symbol", "report_date", "entry_date", "exit_date"])


# ── 3. Option pre-selection (the heart of the strategy) ───────────────────


def _score(row: pd.Series) -> float:
    """Liquidity score = open_interest × volume; missing values → 0."""
    oi = row.get("open_interest", 0) or 0
    vol = row.get("volume", 0) or 0
    try:
        return float(oi) * float(vol)
    except (TypeError, ValueError):
        return 0.0


def _ensure_dte_column(options_df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``dte`` column if missing (optopsy caches it; synthetic data may not)."""
    if "dte" in options_df.columns:
        return options_df
    df = options_df.copy()
    df["dte"] = (pd.to_datetime(df["expiration"]) - pd.to_datetime(df["quote_date"])).dt.days
    return df


def _pick_top(pool: pd.DataFrame, target: float) -> pd.Series | None:
    """Return the row with the highest OI×Volume score, ties broken by strike distance."""
    if pool.empty:
        return None
    scored = pool.assign(_score=pool.apply(_score, axis=1))
    top_score = scored["_score"].max()
    top = scored[scored["_score"] == top_score]
    if len(top) > 1:
        # Tie-break: smallest |strike - target|; default to call on further tie.
        top = top.assign(_dist=(top["strike"] - target).abs())
        top = top.sort_values("_dist", ascending=True)
    return top.iloc[0]


def _select_candidate(
    options_df: pd.DataFrame,
    opt_type: str,
    target: float,
    tol: float,
    min_oi: int,
    min_volume: int,
    max_dte: int,
) -> pd.Series | None:
    """Pick the top-scoring row in ``options_df`` matching the side + strike band.

    Returns ``None`` if no row satisfies all filters.
    """
    pool = options_df[options_df["option_type"] == opt_type].copy()
    if pool.empty:
        return None
    # Strike band
    pool = pool[(pool["strike"] >= target - tol) & (pool["strike"] <= target + tol)]
    if pool.empty:
        return None
    # DTE cap
    if "dte" in pool.columns:
        pool = pool[pool["dte"] <= max_dte]
    if pool.empty:
        return None
    # Liquidity thresholds
    oi = pool["open_interest"].fillna(0)
    vol = pool["volume"].fillna(0)
    pool = pool[(oi >= min_oi) & (vol >= min_volume)]
    if pool.empty:
        return None
    # Ask must be a valid positive price
    ask = pool["ask"].fillna(0)
    pool = pool[ask > 0]
    if pool.empty:
        return None
    return _pick_top(pool, target)


def select_options_for_events(
    options_df: pd.DataFrame,
    stock_df: pd.DataFrame,
    earnings_events: pd.DataFrame,
    config: EarningsOvernightConfig,
) -> pd.DataFrame:
    """For each event, select the top-scoring 2% OTM option (call or put).

    The result is a filtered ``options_df`` with at most one row per
    event. Events that fail the OI/Volume thresholds or whose top
    candidate's cost exceeds ``cost_cap_usd`` are silently dropped.

    Algorithm (per event):

    1. Pick the T-1 reference price from ``stock_df`` (default
       ``config.reference_price="high"``; falls back to ``close``).
    2. Compute ``call_target = ref * (1 + otm)`` and
       ``put_target = ref * (1 - otm)`` with a ``± tol`` strike band.
    3. Filter ``options_df`` to that event's
       ``(symbol, quote_date == entry_date)`` slice.
    4. For each side, pick the top-scoring candidate inside the strike
       band, subject to ``min_oi``, ``min_volume``, ``dte <= max_dte``,
       and ``ask > 0``.
    5. Pick the side with the higher OI×Volume score (the other side
       loses). Tie-break: smaller strike distance from target; final tie
       defaults to call.
    6. Compute ``cost = ask * multiplier * quantity``; drop the event if
       it exceeds ``cost_cap_usd``.
    """
    if earnings_events.empty:
        return options_df.iloc[0:0].copy()

    options_df = _ensure_dte_column(options_df)
    # Build per-symbol, per-date slices for fast lookup.
    by_sym_date: dict[tuple[str, pd.Timestamp], pd.DataFrame] = {
        (sym, pd.Timestamp(qd)): group
        for (sym, qd), group in options_df.groupby(["underlying_symbol", "quote_date"], sort=False)
    }
    # Build per-symbol, per-date stock slices for reference-price lookup.
    stock_by_sym_date: dict[tuple[str, pd.Timestamp], pd.Series] = {}
    for (sym, qd), group in stock_df.groupby(["underlying_symbol", "quote_date"], sort=False):
        if len(group):
            stock_by_sym_date[(sym, pd.Timestamp(qd))] = group.iloc[0]

    selected_rows: list[pd.Series] = []

    for _, event in earnings_events.iterrows():
        sym = event["underlying_symbol"]
        entry_date = pd.Timestamp(event["entry_date"])
        ref_row = stock_by_sym_date.get((sym, entry_date))
        if ref_row is None:
            continue

        ref_price = _reference_price(ref_row, config.reference_price)
        if ref_price is None or ref_price <= 0:
            continue

        call_target = ref_price * (1.0 + config.otm_target_pct)
        put_target = ref_price * (1.0 - config.otm_target_pct)
        tol = ref_price * config.otm_tolerance_pct

        chain = by_sym_date.get((sym, entry_date))
        if chain is None or chain.empty:
            continue

        call_pick = _select_candidate(
            chain, "c", call_target, tol, config.min_oi, config.min_volume, config.max_entry_dte
        )
        put_pick = _select_candidate(
            chain, "p", put_target, tol, config.min_oi, config.min_volume, config.max_entry_dte
        )

        winner = _pick_winner(call_pick, put_pick, call_target, put_target)
        if winner is None:
            continue

        # Cost cap (skip if it would bust the budget)
        ask = float(winner.get("ask", 0) or 0)
        cost = ask * config.multiplier * config.quantity
        if cost > config.cost_cap_usd:
            logger.debug(
                "Skipping event %s entry %s: cost %.2f exceeds cap %.2f",
                sym,
                entry_date.date(),
                cost,
                config.cost_cap_usd,
            )
            continue

        selected_rows.append(winner)

    if not selected_rows:
        return options_df.iloc[0:0].copy()
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def _reference_price(stock_row: pd.Series, mode: str) -> float | None:
    """Pull the configured reference price off a stock row, with fallbacks."""
    primary = stock_row.get(mode)
    if primary is not None and not pd.isna(primary) and float(primary) > 0:
        return float(primary)
    # Fallback chain: high → close → open
    for fallback in ("high", "close", "open"):
        if fallback == mode:
            continue
        v = stock_row.get(fallback)
        if v is not None and not pd.isna(v) and float(v) > 0:
            warnings.warn(
                f"reference_price={mode!r} not available; falling back to {fallback!r}",
                UserWarning,
                stacklevel=3,
            )
            return float(v)
    return None


def _pick_winner(
    call_pick: pd.Series | None,
    put_pick: pd.Series | None,
    call_target: float,
    put_target: float,
) -> pd.Series | None:
    """Pick the side with the higher OI×Volume score; default to call on final tie."""
    if call_pick is None and put_pick is None:
        return None
    if call_pick is None:
        return put_pick
    if put_pick is None:
        return call_pick
    call_score = _score(call_pick)
    put_score = _score(put_pick)
    if call_score > put_score:
        return call_pick
    if put_score > call_score:
        return put_pick
    # Tie — break by strike distance from target
    call_dist = abs(float(call_pick["strike"]) - call_target)
    put_dist = abs(float(put_pick["strike"]) - put_target)
    if call_dist < put_dist:
        return call_pick
    if put_dist < call_dist:
        return put_pick
    # Final tie: default to call
    return call_pick


# ── 4. Side split (last-mile dispatch helper) ──────────────────────────────


def split_options_by_side(
    options_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a pre-selected options_df into (calls_df, puts_df).

    Each DataFrame has at most one row per (symbol, date) because the
    upstream selector pre-deduplicated them.
    """
    if options_df is None or options_df.empty:
        empty = options_df.iloc[0:0].copy() if options_df is not None else pd.DataFrame()
        return empty, empty.copy()
    calls = options_df[options_df["option_type"] == "c"].copy()
    puts = options_df[options_df["option_type"] == "p"].copy()
    return calls, puts
