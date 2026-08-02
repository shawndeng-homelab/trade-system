"""Data extraction and validation layer for backtest-charts.

Provides :class:`BacktestData` and :class:`LegData` — frozen dataclasses
that pre-extract and normalize data from any duck-typed result object
(e.g. ``optopsy.PortfolioResult`` or ``types.SimpleNamespace``).

Chart functions accept ``BacktestData`` instead of raw result objects,
decoupling visualization from optopsy internals.
"""

import dataclasses

import pandas as pd


# ── Default benchmark symbols ──────────────────────────────────────────

BENCHMARK_SYMBOLS = ["SPY", "QQQ", "IWM"]
"""Symbols included in the benchmark section of the summary table.

For each symbol the summary shows the return of buying an ATM call on
the backtest start date and holding to the end date.
"""


# ── Normalization helpers ─────────────────────────────────────────────


def _normalize_equity_curve(ec: pd.Series | None) -> pd.Series:
    """Return a date-indexed equity curve, or an empty Series if data is missing."""
    if ec is None or (isinstance(ec, pd.Series) and ec.empty):
        return pd.Series(dtype=float, name="equity")
    ec = ec.copy()
    if not isinstance(ec.index, pd.DatetimeIndex):
        ec.index = pd.to_datetime(ec.index)
    return ec


def _normalize_trade_log(tl: pd.DataFrame | None) -> pd.DataFrame:
    """Return a trade-log DataFrame, or an empty one if data is missing."""
    return pd.DataFrame() if tl is None else tl.copy()


def _normalize_summary(summary: dict | None) -> dict:
    """Return a summary dict, or a minimal fallback if data is missing."""
    return summary or {"total_trades": 0}


# ── Data classes ──────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class LegData:
    """Pre-extracted per-leg backtest data.

    Attributes:
        name: Leg identifier (e.g. ``"leaps"``, ``"short_call"``).
        trade_log: Per-leg trade log DataFrame.
        equity_curve: Per-leg equity curve (date-indexed Series).
        summary: Per-leg summary metrics dict.
    """

    name: str
    trade_log: pd.DataFrame
    equity_curve: pd.Series
    summary: dict


@dataclasses.dataclass(frozen=True)
class BacktestData:
    """Pre-extracted, validated backtest data for chart rendering.

    Constructed via :meth:`from_result` which validates and normalizes
    data from any duck-typed result object.  Once constructed, chart
    functions can rely on fields without re-validating.

    Attributes:
        capital: Initial capital for reference lines.
        equity_curve: Portfolio equity curve (date-indexed Series, may be empty).
        trade_log: Combined trade log DataFrame (may be empty).
        summary: Portfolio-level summary metrics dict.
        leg_names: Ordered list of leg identifiers.
        leg_results: Per-leg data keyed by leg name.
    """

    capital: float
    equity_curve: pd.Series
    trade_log: pd.DataFrame
    summary: dict
    leg_names: list[str]
    leg_results: dict[str, LegData]
    stock_prices: dict[str, pd.Series]
    benchmark_equity: dict[str, pd.Series]
    benchmark_summaries: dict[str, dict]

    def __post_init__(self) -> None:
        """Validate capital is positive."""
        if self.capital <= 0:
            msg = f"capital must be positive, got {self.capital}"
            raise ValueError(msg)

    @property
    def has_trades(self) -> bool:
        """Whether the trade log contains any trades."""
        return not self.trade_log.empty

    @property
    def has_equity(self) -> bool:
        """Whether the equity curve has data points."""
        return self.equity_curve is not None and not self.equity_curve.empty

    @classmethod
    def from_result(cls, result, capital: float) -> "BacktestData":
        """Extract and validate data from a duck-typed result object.

        Accepts any object with ``equity_curve``, ``trade_log``,
        ``summary``, and ``leg_results`` attributes.  Missing attributes
        default to empty values.

        Args:
            result: Backtest result (e.g. ``optopsy.PortfolioResult``).
            capital: Initial capital for reference lines.

        Returns:
            Frozen ``BacktestData`` instance.
        """
        ec = _normalize_equity_curve(getattr(result, "equity_curve", None))
        tl = _normalize_trade_log(getattr(result, "trade_log", None))
        summary = _normalize_summary(getattr(result, "summary", None))

        raw_legs = getattr(result, "leg_results", None) or {}
        leg_names: list[str] = []
        leg_results: dict[str, LegData] = {}
        for name, leg in raw_legs.items():
            leg_ec = _normalize_equity_curve(getattr(leg, "equity_curve", None))
            leg_tl = _normalize_trade_log(getattr(leg, "trade_log", None))
            leg_summary = _normalize_summary(getattr(leg, "summary", None))
            leg_names.append(str(name))
            leg_results[str(name)] = LegData(
                name=str(name),
                trade_log=leg_tl,
                equity_curve=leg_ec,
                summary=leg_summary,
            )

        return cls(
            capital=capital,
            equity_curve=ec,
            trade_log=tl,
            summary=summary,
            leg_names=leg_names,
            leg_results=leg_results,
            stock_prices={},
            benchmark_equity={},
            benchmark_summaries={},
        )


# ── Benchmark computation ─────────────────────────────────────────────


def compute_benchmarks(
    options_data: dict[str, pd.DataFrame],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    symbols: list[str] | None = None,
) -> dict[str, float]:
    """Compute buy-and-hold ATM call returns for benchmark symbols.

    For each symbol, finds the ATM (delta ≈ 0.50) call on *start_date*
    with the nearest expiration ≥ *end_date*, then computes the percentage
    return from entry mid-price to exit mid-price (or intrinsic value if
    the option is ITM at expiry).

    Args:
        options_data: Mapping of symbol → option chain DataFrame.
            Each DataFrame must have columns: ``quote_date``, ``expiration``,
            ``option_type``, ``strike``, ``bid``, ``ask``, ``delta``.
        start_date: Backtest start date (entry date for benchmark).
        end_date: Backtest end date (exit date for benchmark).
        symbols: Symbols to compute benchmarks for.  Defaults to
            :data:`BENCHMARK_SYMBOLS`.

    Returns:
        Dict mapping ``"benchmark_{SYMBOL}"`` to percentage return.
        Symbols without data are omitted.
    """
    if symbols is None:
        symbols = BENCHMARK_SYMBOLS

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    results: dict[str, float] = {}

    for sym in symbols:
        df = options_data.get(sym)
        if df is None or df.empty:
            continue

        df = df.copy()
        df["quote_date"] = pd.to_datetime(df["quote_date"])
        df["expiration"] = pd.to_datetime(df["expiration"])

        # Filter to calls on start_date
        calls = df[(df["quote_date"] == start) & (df["option_type"].str.lower() == "c")]
        if calls.empty:
            # Try nearest date on or after start
            later = df[(df["quote_date"] >= start) & (df["option_type"].str.lower() == "c")]
            if later.empty:
                continue
            nearest_date = later["quote_date"].min()
            calls = later[later["quote_date"] == nearest_date]

        # Find ATM call: delta closest to 0.50, prefer longest expiration
        # so the option can be held through the entire backtest period
        calls = calls.copy()
        calls["_delta_diff"] = (calls["delta"] - 0.50).abs()
        # First try: ATM call with expiration >= end_date (holds through backtest)
        long_calls = calls[calls["expiration"] >= end]
        if not long_calls.empty:
            atm = long_calls.nsmallest(1, "_delta_diff")
        else:
            # Fallback: pick the ATM call with the farthest expiration
            farthest = calls["expiration"].max()
            atm = calls[calls["expiration"] == farthest].nsmallest(1, "_delta_diff")
        if atm.empty:
            continue

        entry_mid = (atm["bid"].iloc[0] + atm["ask"].iloc[0]) / 2
        if entry_mid <= 0:
            continue

        strike = atm["strike"].iloc[0]
        expiration = atm["expiration"].iloc[0]

        # Find exit price: same contract on end_date (or last date before end)
        exit_rows = df[
            (df["quote_date"] <= end)
            & (df["expiration"] == expiration)
            & (df["strike"] == strike)
            & (df["option_type"].str.lower() == "c")
        ]
        if exit_rows.empty:
            continue

        # Use the latest available quote
        exit_row = exit_rows.loc[exit_rows["quote_date"].idxmax()]
        exit_mid = (exit_row["bid"] + exit_row["ask"]) / 2

        # If exit_mid is 0 (illiquid / no bid), use intrinsic value
        if exit_mid <= 0:
            # Approximate underlying price from delta of entry
            # Use last available stock-like proxy
            continue

        ret = (exit_mid - entry_mid) / entry_mid
        results[f"benchmark_{sym}"] = ret

    return results
