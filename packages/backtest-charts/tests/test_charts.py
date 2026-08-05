r"""Tests for backtest_charts: verify chart functions work with real PortfolioResult data.

Uses a pickled PortfolioResult fixture generated from an actual PMCC backtest on
SPY (100 trades across leaps + short_call legs). Regenerate via::

    uv run --all-packages python -c "
        import pickle
        from options_strategies.pmcc import PmccConfig, run_pmcc
        from options_strategies.shared import load_pmcc_data
        cfg = PmccConfig(symbol='SPY', capital=100_000.0, quantity=1, multiplier=100,
                         max_positions=1, leaps_delta=0.80, leaps_delta_min=0.75,
                         leaps_delta_max=0.80, leaps_max_entry_dte=365, leaps_exit_dte=30,
                         short_delta=0.30, short_delta_min=0.20, short_delta_max=0.30,
                         short_max_entry_dte=30, short_exit_dte=7, short_take_profit=0.8,
                         short_stop_loss=-0.11, leaps_weight=0.6, short_weight=0.4)
        opts, stk = load_pmcc_data(cfg.symbol, start_date=cfg.start_date,
                                   end_date=cfg.end_date, expiration_type=cfg.expiration_type)
        result = run_pmcc(opts, stk, cfg)
        with open('packages/backtest-charts/tests/fixtures/portfolio_result.pkl', 'wb') as f:
            pickle.dump(result, f)
    "
"""

import os
import pickle
import tempfile
import types
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from backtest_charts import PANEL_REGISTRY
from backtest_charts import BacktestData
from backtest_charts import BacktestReport
from backtest_charts import plot_cumulative_pnl
from backtest_charts import plot_dashboard
from backtest_charts import plot_equity_curve
from backtest_charts import plot_exit_breakdown
from backtest_charts import plot_pnl_distribution
from backtest_charts import plot_portfolio
from backtest_charts._util import _empty_chart
from backtest_charts.summary import plot_summary


_FIXTURE = Path(__file__).parent / "fixtures" / "portfolio_result.pkl"


# ── Fixtures ──────────────────────────────────────────────────────────────


def _load_result():
    """Load the real PortfolioResult fixture, or build an empty fallback."""
    if _FIXTURE.exists():
        with open(_FIXTURE, "rb") as f:
            return pickle.load(f)
    return _empty_result()


def _empty_result():
    """Build an empty result (no trades) for edge-case tests."""
    return types.SimpleNamespace(
        trade_log=pd.DataFrame(),
        equity_curve=pd.Series(dtype=float, name="equity"),
        summary={"total_trades": 0},
        leg_results={},
    )


def _make_report(result=None, capital=100_000.0):
    """Create a BacktestReport from the fixture or given result."""
    return BacktestReport(result or _load_result(), capital=capital)


# ══════════════════════════════════════════════════════════════════════════
# BacktestData tests
# ══════════════════════════════════════════════════════════════════════════


class TestBacktestData:
    """BacktestData extraction and validation."""

    def test_from_result_extracts_fields(self) -> None:
        """from_result extracts all fields from a real PortfolioResult."""
        result = _load_result()
        data = BacktestData.from_result(result, 100_000.0)
        assert data.capital == 100_000.0
        assert data.has_equity
        assert data.has_trades
        assert len(data.trade_log) >= 50
        assert "leg" in data.trade_log.columns
        assert len(data.leg_names) == 2
        assert "leaps" in data.leg_results
        assert "short_call" in data.leg_results

    def test_from_result_handles_empty(self) -> None:
        """from_result handles empty result gracefully."""
        data = BacktestData.from_result(_empty_result(), 50_000.0)
        assert not data.has_trades
        assert not data.has_equity
        assert data.capital == 50_000.0
        assert data.leg_names == []
        assert data.benchmark_equity == {}

    def test_from_result_initializes_benchmark_equity(self) -> None:
        """from_result initializes benchmark_equity as an empty dict."""
        data = BacktestData.from_result(_load_result(), 100_000.0)
        assert data.benchmark_equity == {}

    def test_from_result_handles_missing_attrs(self) -> None:
        """from_result handles objects missing optional attributes."""
        minimal = types.SimpleNamespace()
        data = BacktestData.from_result(minimal, 10_000.0)
        assert not data.has_trades
        assert not data.has_equity

    def test_capital_must_be_positive(self) -> None:
        """from_result rejects non-positive capital."""
        with pytest.raises(ValueError, match="capital must be positive"):
            BacktestData.from_result(_empty_result(), 0)
        with pytest.raises(ValueError, match="capital must be positive"):
            BacktestData.from_result(_empty_result(), -100)

    def test_frozen_immutability(self) -> None:
        """BacktestData is frozen and cannot be modified."""
        data = BacktestData.from_result(_empty_result(), 10_000.0)
        with pytest.raises(AttributeError):
            data.capital = 999  # type: ignore[misc]

    def test_has_trades_property(self) -> None:
        """has_trades reflects trade_log emptiness."""
        assert not BacktestData.from_result(_empty_result(), 10_000.0).has_trades
        assert BacktestData.from_result(_load_result(), 100_000.0).has_trades

    def test_has_equity_property(self) -> None:
        """has_equity reflects equity_curve emptiness."""
        assert not BacktestData.from_result(_empty_result(), 10_000.0).has_equity
        assert BacktestData.from_result(_load_result(), 100_000.0).has_equity


# ══════════════════════════════════════════════════════════════════════════
# BacktestReport tests
# ══════════════════════════════════════════════════════════════════════════


class TestBacktestReport:
    """BacktestReport OOP API tests."""

    def test_construction(self) -> None:
        """BacktestReport constructs from a real result."""
        report = _make_report()
        assert report.capital == 100_000.0
        assert report.data.has_trades

    def test_plot_equity_returns_figure(self) -> None:
        """plot_equity returns a Figure with traces and a reference line."""
        report = _make_report()
        fig = report.plot_equity()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1
        assert len(fig.layout.shapes) >= 1

    def test_plot_cum_pnl_returns_figure(self) -> None:
        """plot_cum_pnl returns a Figure with traces per leg."""
        report = _make_report()
        fig = report.plot_cum_pnl()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_plot_pnl_dist_returns_figure(self) -> None:
        """plot_pnl_dist returns a Figure with a bar trace."""
        report = _make_report()
        fig = report.plot_pnl_dist()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_plot_exits_returns_figure(self) -> None:
        """plot_exits returns a Figure with stacked bar traces."""
        report = _make_report()
        fig = report.plot_exits()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_plot_summary_returns_figure(self) -> None:
        """plot_summary returns a Figure with a table trace."""
        report = _make_report()
        fig = report.plot_summary()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_plot_trades_returns_table(self) -> None:
        """plot_trades returns a standalone Table figure with one row per trade."""
        report = _make_report()
        fig = report.plot_trades()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        table = fig.data[0]
        assert isinstance(table, go.Table)
        # One value list per displayed column, each as long as the trade log
        n_trades = len(report.data.trade_log)
        assert all(len(col) == n_trades for col in table.cells.values)

    def test_plot_trades_max_height_override(self) -> None:
        """plot_trades honours an explicit max_height."""
        report = _make_report()
        default_fig = report.plot_trades()
        tall_fig = report.plot_trades(max_height=2000)
        assert tall_fig.layout.height == 2000
        assert default_fig.layout.height != 2000

    def test_dashboard_has_default_panels(self) -> None:
        """Dashboard includes all 5 default panels (trade_log is standalone)."""
        report = _make_report()
        fig = report.plot_dashboard()
        assert isinstance(fig, go.Figure)
        # 5 panels: equity + cum_pnl + pnl_dist + exits + summary
        assert len(fig.data) >= 5

    def test_dashboard_subplot_titles(self) -> None:
        """Dashboard subplot titles contain all 5 panel titles."""
        report = _make_report()
        fig = report.plot_dashboard()
        titles = [ann.text for ann in fig.layout.annotations if ann.text]
        assert "Portfolio Equity Curve" in titles
        assert "Cumulative P&L by Leg" in titles
        assert "Strategy Summary" in titles

    def test_save_html(self) -> None:
        """save_html writes an HTML file with embedded Plotly."""
        report = _make_report()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test_dashboard.html")
            path = report.save_html(path=out)
            assert os.path.isfile(path)
            content = Path(path).read_text(encoding="utf-8")
            assert "plotly" in content
            assert "<html>" in content

    def test_save_html_returns_absolute_path(self) -> None:
        """save_html returns an absolute path."""
        report = _make_report()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test.html")
            path = report.save_html(path=out)
            assert os.path.isabs(path)

    def test_empty_data_dashboard(self) -> None:
        """Empty result still produces a renderable dashboard."""
        report = BacktestReport(_empty_result(), capital=10_000.0)
        fig = report.plot_dashboard()
        assert isinstance(fig, go.Figure)
        fig.to_dict()  # should not raise

    def test_benchmark_results_injects_equity(self) -> None:
        """benchmark_results parameter injects equity curves into data."""
        result = _load_result()
        bm_ec = pd.Series(
            [100_000, 101_000, 102_000],
            index=pd.to_datetime(["2024-08-01", "2024-08-02", "2024-08-03"]),
        )
        bm_result = types.SimpleNamespace(equity_curve=bm_ec)
        report = BacktestReport(
            result,
            capital=100_000.0,
            benchmark_results={"SPY ATM": bm_result},
        )
        assert "SPY ATM" in report.data.benchmark_equity
        assert len(report.data.benchmark_equity["SPY ATM"]) == 3

    def test_benchmark_results_without_equity_curve(self) -> None:
        """benchmark_results with missing equity_curve is handled gracefully."""
        result = _load_result()
        bm_result = types.SimpleNamespace()  # no equity_curve attribute
        report = BacktestReport(
            result,
            capital=100_000.0,
            benchmark_results={"SPY ATM": bm_result},
        )
        assert report.data.benchmark_equity == {}

    def test_plot_equity_with_benchmark_overlay(self) -> None:
        """plot_equity renders benchmark overlay traces when benchmark_equity is populated."""
        result = _load_result()
        # Use dates that overlap with the fixture equity curve (2024-07-31 to 2026-07-21)
        bm_ec = pd.Series(
            [100_000, 101_000, 102_000],
            index=pd.to_datetime(["2024-08-01", "2024-08-02", "2024-08-03"]),
        )
        bm_result = types.SimpleNamespace(equity_curve=bm_ec)
        report = BacktestReport(
            result,
            capital=100_000.0,
            benchmark_results={"SPY ATM": bm_result},
        )
        fig = report.plot_equity()
        assert isinstance(fig, go.Figure)
        # Should have at least 2 traces: strategy equity + benchmark overlay
        assert len(fig.data) >= 2


# ══════════════════════════════════════════════════════════════════════════
# Summary panel tests
# ══════════════════════════════════════════════════════════════════════════


class TestSummaryPanel:
    """Summary go.Table panel tests."""

    def test_summary_renders_table(self) -> None:
        """Summary produces a Table trace with metrics."""
        data = BacktestData.from_result(_load_result(), 100_000.0)
        fig = plot_summary(data)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Table)

    def test_summary_has_all_metrics(self) -> None:
        """Summary table contains all expected metric groups."""
        data = BacktestData.from_result(_load_result(), 100_000.0)
        fig = plot_summary(data)
        table = fig.data[0]
        metric_names = table.cells.values[0]  # type: ignore[index]
        # Check group headers are present
        name_strs = [str(n) for n in metric_names]
        assert any("Performance" in n for n in name_strs)
        assert any("Risk" in n for n in name_strs)
        assert any("Trading" in n for n in name_strs)

    def test_summary_empty_data(self) -> None:
        """Empty data returns a placeholder figure."""
        data = BacktestData.from_result(_empty_result(), 10_000.0)
        fig = plot_summary(data)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0  # placeholder has no traces


# ══════════════════════════════════════════════════════════════════════════
# Panel extension tests
# ══════════════════════════════════════════════════════════════════════════


class TestPanelExtension:
    """Custom panel registration and per-instance isolation."""

    def test_panel_decorator(self) -> None:
        """@report.panel registers a custom panel."""
        report = _make_report()
        assert "custom" not in report.list_panels()

        @report.panel("custom")
        def custom(data: BacktestData) -> go.Figure:
            return _empty_chart("Custom", "test")

        assert "custom" in report.list_panels()
        fig = report.plot_dashboard()
        titles = [ann.text for ann in fig.layout.annotations if ann.text]
        assert "Custom" in titles

    def test_add_and_remove_panel(self) -> None:
        """add_panel and remove_panel work correctly."""
        report = _make_report()
        original_count = len(report.list_panels())
        report.add_panel("extra", lambda data: _empty_chart("Extra", "test"))
        assert len(report.list_panels()) == original_count + 1
        report.remove_panel("extra")
        assert "extra" not in report.list_panels()

    def test_remove_default_panel(self) -> None:
        """Removing a default panel reduces the dashboard."""
        report = _make_report()
        report.remove_panel("exit_breakdown")
        assert "exit_breakdown" not in report.list_panels()
        fig = report.plot_dashboard()
        # Should have fewer traces than with 5 panels
        assert isinstance(fig, go.Figure)

    def test_per_instance_isolation(self) -> None:
        """Different report instances have independent panel registries."""
        r1 = _make_report()
        r2 = _make_report()
        r1.remove_panel("exit_breakdown")
        assert "exit_breakdown" not in r1.list_panels()
        assert "exit_breakdown" in r2.list_panels()

    def test_list_panels_default(self) -> None:
        """Default panels are registered in order; trade_log is not one of them."""
        report = _make_report()
        keys = report.list_panels()
        assert keys == ["equity_curve", "cumulative_pnl", "pnl_distribution", "exit_breakdown", "summary"]
        assert "trade_log" not in keys


# ══════════════════════════════════════════════════════════════════════════
# Legacy API tests (backward compat)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestLegacyRealDataRendering:
    """Legacy function API still works with real data."""

    def test_fixture_loaded(self) -> None:
        """The real-data fixture is present with trades."""
        result = _load_result()
        assert not result.trade_log.empty
        assert len(result.trade_log) >= 50

    def test_equity_curve_renders(self) -> None:  # noqa: D102
        result = _load_result()
        fig = plot_equity_curve(result, 100_000.0)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_cumulative_pnl_renders(self) -> None:  # noqa: D102
        result = _load_result()
        fig = plot_cumulative_pnl(result)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_pnl_distribution_renders(self) -> None:  # noqa: D102
        result = _load_result()
        fig = plot_pnl_distribution(result)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_exit_breakdown_renders(self) -> None:  # noqa: D102
        result = _load_result()
        fig = plot_exit_breakdown(result)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_dashboard_renders(self) -> None:  # noqa: D102
        result = _load_result()
        fig = plot_dashboard(result, 100_000.0)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 4


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestLegacyChartTypes:
    """Legacy functions return go.Figure."""

    def test_equity_curve_returns_figure(self) -> None:  # noqa: D102
        fig = plot_equity_curve(_load_result(), 100_000.0)
        assert isinstance(fig, go.Figure)

    def test_dashboard_returns_figure(self) -> None:  # noqa: D102
        fig = plot_dashboard(_load_result(), 100_000.0)
        assert isinstance(fig, go.Figure)
        assert hasattr(fig, "write_html")


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestLegacyHtmlOutput:
    """Legacy plot_portfolio writes valid HTML."""

    def test_portfolio_saves_html(self) -> None:  # noqa: D102
        result = _load_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test_dashboard.html")
            path = plot_portfolio(result, 100_000.0, out_path=out)
            assert os.path.isfile(path)
            content = Path(path).read_text(encoding="utf-8")
            assert "plotly" in content
            assert "<html>" in content

    def test_portfolio_returns_absolute_path(self) -> None:  # noqa: D102
        result = _load_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test.html")
            path = plot_portfolio(result, 100_000.0, out_path=out)
            assert os.path.isabs(path)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestLegacyEmptyData:
    """Legacy functions handle empty data gracefully."""

    def test_equity_curve_empty(self) -> None:  # noqa: D102
        fig = plot_equity_curve(_empty_result(), 100_000.0)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_cumulative_pnl_empty(self) -> None:  # noqa: D102
        fig = plot_cumulative_pnl(_empty_result())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_pnl_distribution_empty(self) -> None:  # noqa: D102
        fig = plot_pnl_distribution(_empty_result())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_exit_breakdown_empty(self) -> None:  # noqa: D102
        fig = plot_exit_breakdown(_empty_result())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_dashboard_empty(self) -> None:  # noqa: D102
        fig = plot_dashboard(_empty_result(), 100_000.0)
        assert isinstance(fig, go.Figure)
        fig.to_dict()


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestLegacyPanelRegistry:
    """Legacy PANEL_REGISTRY still works."""

    def test_default_panels_registered(self) -> None:  # noqa: D102
        assert "equity_curve" in PANEL_REGISTRY
        assert "cumulative_pnl" in PANEL_REGISTRY
        assert "pnl_distribution" in PANEL_REGISTRY
        assert "exit_breakdown" in PANEL_REGISTRY

    def test_deregister_and_reregister(self) -> None:  # noqa: D102
        factory = PANEL_REGISTRY["exit_breakdown"]
        PANEL_REGISTRY.deregister("exit_breakdown")
        assert "exit_breakdown" not in PANEL_REGISTRY
        # Re-register to restore defaults
        PANEL_REGISTRY.register("exit_breakdown", factory)

    def test_custom_panel(self) -> None:  # noqa: D102
        PANEL_REGISTRY.register("custom", lambda data: _empty_chart("Custom", "test"))
        result = _load_result()
        fig = plot_dashboard(result, 100_000.0)
        titles = [ann.text for ann in fig.layout.annotations if ann.text]
        assert "Custom" in titles
        # Clean up
        PANEL_REGISTRY.deregister("custom")
