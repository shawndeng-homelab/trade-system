"""Rendering and export tests for the duck-typed research report interface."""

from types import SimpleNamespace

import pandas as pd
import pytest
from backtest_charts import BacktestReport
from options_strategies.evaluation import EvaluationResult
from options_strategies.evaluation import build_pmcc_evaluation
from options_strategies.pmcc import PmccConfig


@pytest.fixture
def evaluation():
    """A completed trade opened before the price-reference coverage begins."""
    trades = pd.DataFrame(
        {
            "leg": ["leaps", "short_call"],
            "entry_date": pd.to_datetime(["2024-01-01", "2024-02-02"]),
            "exit_date": pd.to_datetime(["2024-04-01", "2024-03-01"]),
            "realized_pnl": [100.0, -10.0],
            "quantity": [1, 1],
            "multiplier": [100, 100],
            "exit_type": ["expiration", "stop_loss"],
        }
    )
    stock = pd.DataFrame({"quote_date": pd.date_range("2024-02-01", "2024-04-01"), "close": 100.0})
    return build_pmcc_evaluation(SimpleNamespace(trade_log=trades), stock, PmccConfig(capital=1000))


def test_views_have_correct_dates_and_baselines(evaluation):
    """Shared-window returns include earlier opening fees in the starting equity."""
    full = BacktestReport.from_evaluation(evaluation)
    common = BacktestReport.from_evaluation(evaluation, scope="common")
    assert full.data.equity_curve.index[0] == pd.Timestamp("2024-01-01")
    assert common.data.equity_curve.index[0] == pd.Timestamp("2024-02-01")
    assert common.data.capital == pytest.approx(998.35)
    assert common.capital == full.capital == 1000
    assert common.data.summary["total_return"] == pytest.approx(1083.4 / 998.35 - 1)
    assert not common.data.stock_prices  # Price reference must not share the risk-comparison panel.


def test_dashboard_structure_and_scope(evaluation):
    """The main curves share a basis; price reference lives in its own panel."""
    report = BacktestReport.from_evaluation(evaluation)
    figure = report.plot_dashboard()
    assert sum(t.type == "indicator" for t in figure.data) == 4
    assert any(t.type == "histogram" for t in figure.data)
    assert any(t.type == "heatmap" for t in figure.data)
    assert figure.layout.xaxis2.matches == "x"
    main = next(t for t in figure.data if t.name == "PMCC")
    stock = next(t for t in figure.data if t.name == "SPY price")
    assert main.xaxis != stock.xaxis
    assert "completed trades only" in figure.layout.title.text
    assert figure.layout.hovermode == "x unified"


def test_html_export_and_restored_report(evaluation, tmp_path):
    """Saved artifacts rebuild without market downloads and export complete records."""
    evaluation.save(tmp_path / "evaluation")
    restored = EvaluationResult.load(tmp_path / "evaluation")
    report = BacktestReport.from_evaluation(restored)
    path = tmp_path / "report.html"
    report.save_html(str(path))
    content = path.read_text()
    assert "fixed fills" in content
    assert "zero-return control" in content
    assert '<script src="https://cdn.plot.ly' not in content
    assert "Period costs" in content
    report.export_trades(tmp_path / "trades.csv")
    assert len(pd.read_csv(tmp_path / "trades.csv")) == 2


def test_invalid_view_inputs(evaluation):
    """Reject unknown scopes and scenarios instead of silently changing experiments."""
    with pytest.raises(ValueError, match="scope"):
        BacktestReport.from_evaluation(evaluation, scope="unknown")
    with pytest.raises(ValueError, match="scenario"):
        BacktestReport.from_evaluation(evaluation, scenario="unknown")


def test_segment_table_respects_common_scope(evaluation):
    """Every time diagnostic uses the same scope as the displayed equity."""
    report = BacktestReport.from_evaluation(evaluation, scope="common")
    fig = report.plot_segments()
    starts = fig.data[0].cells.values[2]
    assert min(starts) == "2024-02-01"
    assert "descriptive only" in fig.layout.title.text
    with pytest.raises(ValueError, match="kind"):
        report.plot_segments(kind="unknown")


def test_empty_evaluation_dashboard():
    """A zero-trade result still renders indicators and diagnostic tables."""
    stock = pd.DataFrame({"quote_date": pd.date_range("2024-01-01", periods=3), "close": 100.0})
    evaluation = build_pmcc_evaluation(SimpleNamespace(trade_log=pd.DataFrame()), stock, PmccConfig(capital=1000))
    report = BacktestReport.from_evaluation(evaluation)
    figure = report.plot_dashboard()
    assert figure.data[0].value == 0
    assert figure.data[3].value == 0
    assert report.plot_segments().data[0].type == "table"


def test_large_trade_log_preview_and_complete_export(evaluation, tmp_path):
    """The 50-row screen limit must never truncate the exported evidence."""
    trades = pd.concat([evaluation.raw_result.trade_log] * 35, ignore_index=True)
    stock = evaluation.stock_prices.rename("close").rename_axis("quote_date").reset_index()
    large = build_pmcc_evaluation(SimpleNamespace(trade_log=trades), stock, PmccConfig(capital=1000))
    report = BacktestReport.from_evaluation(large)
    table = next(trace for trace in report.plot_dashboard().data if trace.type == "table")
    assert len(table.cells.values[0]) == 50
    report.export_trades(tmp_path / "all.csv")
    assert len(pd.read_csv(tmp_path / "all.csv")) == 70


def test_export_includes_full_roundtrip_costs(evaluation, tmp_path):
    """CSV preserves gross evidence and includes the same net values as the screen."""
    report = BacktestReport.from_evaluation(evaluation, scope="common", scenario="stress")
    report.export_trades(tmp_path / "net.csv")
    table = pd.read_csv(tmp_path / "net.csv")
    assert table.realized_pnl.sum() == 90
    assert table.commission.sum() == pytest.approx(5.2)
    assert table.slippage.sum() == pytest.approx(20)
    assert table.net_trade_pnl.sum() == pytest.approx(64.8)
    assert table.scenario.tolist() == ["stress", "stress"]
