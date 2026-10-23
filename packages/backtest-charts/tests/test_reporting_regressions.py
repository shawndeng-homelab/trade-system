"""Numerical and composition regressions independent of saved engine fixtures."""

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest
from backtest_charts import BacktestData
from backtest_charts import BacktestReport


def _result(values=(1000, 1100, 1210), dates=("2024-01-01", "2025-01-01", "2026-01-01"), summary=None):
    return SimpleNamespace(
        equity_curve=pd.Series(values, index=pd.to_datetime(dates), dtype=float),
        trade_log=pd.DataFrame(),
        summary=summary or {"total_return": 0.21, "total_trades": 5},
    )


def test_report_does_not_mutate_input_summaries():
    """Derived metrics and nested data belong to the report, not its inputs."""
    result = _result(summary={"total_return": 0.21, "metadata": {"name": "original"}})
    benchmark = _result(summary={"total_return": 0.21})
    original, bm_original = deepcopy(result.summary), deepcopy(benchmark.summary)
    report = BacktestReport(result, capital=1000, benchmark_results={"BM": benchmark})
    report.data.summary["metadata"]["name"] = "changed"
    assert result.summary == original
    assert benchmark.summary == bm_original


def test_first_loss_includes_initial_capital_and_entry_date():
    """A sole losing trade must produce a nonzero drawdown."""
    result = _result(values=(900,), dates=("2025-01-01",))
    result.trade_log = pd.DataFrame({"entry_date": ["2024-01-01"], "exit_date": ["2025-01-01"]})
    report = BacktestReport(result, capital=1000)
    assert report.data.summary["max_drawdown"] == pytest.approx(-0.1)
    assert report.data.equity_curve.iloc[0] == 1000
    assert report.data.summary["annualized_return"] == pytest.approx(0.9 ** (365.25 / 366) - 1)
    assert report.data.summary["mar_ratio"] == pytest.approx(report.data.summary["annualized_return"] / 0.1)


def test_benchmark_first_profit_is_not_erased():
    """Benchmark graph and table use the same original-capital denominator."""
    benchmark = _result(values=(1100, 1200, 1300), summary={"total_return": 0.3})
    report = BacktestReport(_result(), capital=1000, benchmark_results={"BM": benchmark})
    trace = report.plot_equity().data[-1]
    assert trace.y[0] == pytest.approx(10)
    assert trace.y[-1] == pytest.approx(30)
    assert report.data.benchmark_summaries["BM"]["total_return"] == pytest.approx(trace.y[-1] / 100)


def test_clipped_comparison_recalculates_both_sides():
    """A longer benchmark cannot contribute full-period statistics to a shorter plot."""
    result = _result(values=(1000, 1100, 1210), dates=("2024-01-01", "2025-01-01", "2026-01-01"))
    benchmark = _result(values=(1000, 1200, 1500), dates=("2023-01-01", "2025-01-01", "2025-07-01"))
    report = BacktestReport(result, capital=1000, benchmark_results={"BM": benchmark}, benchmark_capitals={"BM": 1000})
    assert report.data.equity_curve.index[-1] == pd.Timestamp("2025-07-01")
    assert report.data.summary["total_return"] == pytest.approx(0.1)
    assert report.data.benchmark_summaries["BM"]["total_return"] == pytest.approx(0.5)
    assert "total_trades" not in report.data.summary
    assert "total_trades" not in report.data.benchmark_summaries["BM"]
    curves = report.plot_equity().data
    assert curves[0].x[0] == curves[-1].x[0]
    assert curves[0].x[-1] == curves[-1].x[-1]


def test_benchmark_missing_curve_does_not_crash_or_show_unrelated_metrics():
    """A summary without dates cannot be presented as a comparable benchmark."""
    report = BacktestReport(
        _result(), capital=1000, benchmark_results={"BM": SimpleNamespace(summary={"total_return": 0.3})}
    )
    assert report.data.benchmark_equity == {}
    assert report.data.benchmark_summaries == {}


def test_explicit_capital_handles_bankrupt_benchmark():
    """A -100% return cannot be used to infer capital by division."""
    benchmark = _result(values=(1000, 500, 0), summary={"total_return": -1})
    report = BacktestReport(
        _result(), capital=1000, benchmark_results={"BM": benchmark}, benchmark_capitals={"BM": 1000}
    )
    assert report.data.benchmark_summaries["BM"]["total_return"] == -1
    assert report.data.benchmark_summaries["BM"]["max_drawdown"] == -1


def test_summary_only_equity_is_displayed():
    """Curves without trade logs still have usable return summaries."""
    assert BacktestReport(_result(), capital=1000).plot_summary().data[0].type == "table"


def test_dashboard_preserves_shared_percent_axis_and_reference_annotation():
    """Standalone and composed equity charts preserve identical axis semantics."""
    stocks = pd.DataFrame({"quote_date": pd.to_datetime(["2024-01-01", "2026-01-01"]), "close": [100, 200]})
    report = BacktestReport(_result(), capital=1000, stock_data={"SPY": stocks})
    single, dashboard = report.plot_equity(), report.plot_dashboard()
    assert all(trace.yaxis in (None, "y") for trace in single.data)
    assert dashboard.data[0].yaxis == dashboard.data[1].yaxis == "y"
    assert dashboard.layout.yaxis.ticksuffix == single.layout.yaxis.ticksuffix == "%"
    start = next(ann for ann in dashboard.layout.annotations if ann.text == "Start")
    assert start.xref == "x domain"
    assert start.yref == "y"
    assert dashboard.layout.height > 920
    # The summary needs its own row height, not a compressed 280px panel.
    tables = [trace for trace in dashboard.data if trace.type == "table"]
    summary_table = tables[-1]
    domain_height = summary_table.domain.y[1] - summary_table.domain.y[0]
    available = domain_height * (dashboard.layout.height - 80)
    required = len(summary_table.cells.values[0]) * 24 + 30
    assert available >= required


def test_empty_panel_annotations_stay_inside_their_cells():
    """Paper-relative empty-state messages must become subplot-domain relative."""
    report = BacktestReport(SimpleNamespace(), capital=1000)
    fig = report.plot_dashboard()
    messages = [ann for ann in fig.layout.annotations if ann.text.startswith("No ")]
    assert len(messages) == 6
    assert all(ann.xref.endswith(" domain") and ann.yref.endswith(" domain") for ann in messages)
    assert len({ann.xref for ann in messages}) == 6
    assert fig.layout.xaxis.visible is False


@pytest.mark.parametrize("capital", [0, -1, float("nan"), float("inf")])
def test_invalid_capital_rejected(capital):
    """Invalid bases cannot produce meaningful returns."""
    with pytest.raises(ValueError, match="capital must be positive"):
        BacktestData.from_result(SimpleNamespace(), capital)


@pytest.mark.parametrize("columns", [0, -1, 1.5, True])
def test_dashboard_invalid_columns(columns):
    """Invalid grid sizes produce an actionable error."""
    with pytest.raises(ValueError, match="columns"):
        BacktestReport(_result(), capital=1000).plot_dashboard(columns=columns)


def test_dashboard_with_no_panels():
    """Removing all registered panels is a valid empty dashboard."""
    report = BacktestReport(_result(), capital=1000)
    for key in report.list_panels():
        report.remove_panel(key)
    assert not report.plot_dashboard().data


def test_multiple_benchmarks_have_one_common_window():
    """All curves share dates while report.capital retains the caller's initial capital."""
    late = _result(values=(2000, 2200), dates=("2025-01-01", "2026-01-01"), summary={"total_return": 0.1})
    report = BacktestReport(
        _result(), capital=1000, benchmark_results={"late": late}, benchmark_capitals={"late": 2000}
    )
    assert report.capital == 1000
    assert report.data.capital == 1100
    assert report.data.summary["total_return"] == pytest.approx(0.1)
    assert report.data.benchmark_summaries["late"]["total_return"] == pytest.approx(0.1)
    assert all(trace.y[-1] == pytest.approx(10) for trace in report.plot_equity().data)


def test_no_overlap_is_omitted_with_warning():
    """An unrelated date range cannot silently appear in the comparison table."""
    old = _result(values=(1000, 1100), dates=("2020-01-01", "2021-01-01"))
    with pytest.warns(UserWarning, match="no overlapping"):
        report = BacktestReport(_result(), capital=1000, benchmark_results={"old": old})
    assert not report.data.benchmark_summaries
    assert report.data.equity_curve.index[0] == pd.Timestamp("2024-01-01")


def test_disjoint_benchmarks_reject_empty_common_interval():
    """Individually overlapping benchmarks may still have no shared interval."""
    early = _result(values=(1000, 1100), dates=("2024-01-01", "2024-06-01"))
    late = _result(values=(1000, 1100), dates=("2025-01-01", "2026-01-01"))
    with pytest.raises(ValueError, match="no common"):
        BacktestReport(_result(), capital=1000, benchmark_results={"early": early, "late": late})


def test_curve_without_capital_metadata_warns_and_uses_observed_return():
    """The fallback is explicit and the plot and table still agree."""
    bm = SimpleNamespace(equity_curve=pd.Series([1100, 1210], index=pd.to_datetime(["2024-01-01", "2026-01-01"])))
    with pytest.warns(UserWarning, match="initial capital unavailable"):
        report = BacktestReport(_result(), capital=1000, benchmark_results={"BM": bm})
    assert report.data.benchmark_summaries["BM"]["total_return"] == pytest.approx(0.1)
    assert report.plot_equity().data[-1].y[-1] == pytest.approx(10)
