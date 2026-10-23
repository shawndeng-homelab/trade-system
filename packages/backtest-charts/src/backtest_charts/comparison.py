"""Align strategy and benchmark curves before calculating or plotting returns."""

import dataclasses
import math
import warnings
from copy import deepcopy

import pandas as pd

from backtest_charts.data import BacktestData
from backtest_charts.data import _normalize_equity_curve
from backtest_charts.metrics import curve_metrics


def align_benchmarks(data: BacktestData, results: dict, capitals: dict[str, float]) -> BacktestData:
    """Compare all overlapping curves over their common observed interval.

    Explicit benchmark capital takes precedence. Otherwise infer it from the
    trade ledger or full-period return and final equity, or use the first observation when no
    capital information exists. Never carry equity beyond its observed end.
    """
    if not data.has_equity:
        return data
    curves = {}
    bases = {}
    summaries = {}
    start, end = data.equity_curve.index[[0, -1]]
    for label, result in results.items():
        curve = _normalize_equity_curve(getattr(result, "equity_curve", None))
        if curve.empty:
            continue
        summary = deepcopy(getattr(result, "summary", None) or {})
        log = getattr(result, "trade_log", None)
        base = capitals.get(label)
        if base is None and log is not None and not log.empty and {"equity", "cumulative_pnl"}.issubset(log):
            base = float(log["equity"].iloc[0] - log["cumulative_pnl"].iloc[0])
        if base is None:
            total_return = summary.get("total_return")
            if total_return is not None and math.isfinite(total_return) and total_return > -1:
                base = float(curve.iloc[-1] / (1 + total_return))
            else:
                base = float(curve.iloc[0])
                warnings.warn(
                    f"Benchmark {label!r}: initial capital unavailable; using first observed equity.",
                    UserWarning,
                    stacklevel=3,
                )
        if not math.isfinite(base) or base <= 0:
            raise ValueError(f"Benchmark {label!r} capital must be finite and positive")
        if log is not None and not log.empty and "entry_date" in log:
            entry = pd.to_datetime(log["entry_date"]).min()
            if entry < curve.index[0]:
                curve.loc[entry] = base
                curve = curve.sort_index()
        if curve.index[-1] < start or curve.index[0] > end:
            warnings.warn(f"Benchmark {label!r} has no overlapping equity dates; omitted.", UserWarning, stacklevel=3)
            continue
        curves[label] = curve
        bases[label] = base
        summaries[label] = summary
    if not curves:
        return data
    start = max(start, *(curve.index[0] for curve in curves.values()))
    end = min(end, *(curve.index[-1] for curve in curves.values()))
    if start > end:
        raise ValueError("Benchmarks have no common comparison interval")

    def trim(curve, base):
        clipped = start != curve.index[0] or end != curve.index[-1]
        if start > curve.index[0]:
            base = float(curve.asof(start))
        if not math.isfinite(base) or base <= 0:
            raise ValueError("Comparison interval must start with positive equity")
        index = curve.index[(curve.index >= start) & (curve.index <= end)].union(pd.DatetimeIndex([start, end]))
        return curve.reindex(curve.index.union(index)).ffill().reindex(index), base, clipped

    equity, capital, clipped = trim(data.equity_curve, data.capital)
    # Full-run trade statistics cannot describe a clipped comparison window.
    summary = {} if clipped else dict(data.summary)
    summary.update(curve_metrics(equity, capital))
    aligned, aligned_summaries, aligned_bases = {}, {}, {}
    for label, curve in curves.items():
        curve, base, clipped = trim(curve, bases[label])
        bm_summary = {} if clipped else summaries[label]
        bm_summary.update(curve_metrics(curve, base))
        aligned[label] = curve
        aligned_bases[label] = base
        aligned_summaries[label] = bm_summary
    return dataclasses.replace(
        data,
        capital=capital,
        equity_curve=equity,
        summary=summary,
        benchmark_equity=aligned,
        benchmark_capitals=aligned_bases,
        benchmark_summaries=aligned_summaries,
    )
