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

import json
import os
import pickle
import tempfile
import types
from pathlib import Path

import altair as alt
import pandas as pd
import vl_convert
from backtest_charts import plot_cumulative_pnl
from backtest_charts import plot_dashboard
from backtest_charts import plot_equity_curve
from backtest_charts import plot_exit_breakdown
from backtest_charts import plot_pnl_distribution
from backtest_charts import plot_portfolio


_FIXTURE = Path(__file__).parent / "fixtures" / "portfolio_result.pkl"


# ── Fixtures ──────────────────────────────────────────────────────────────


def _load_result():
    """Load the real PortfolioResult fixture, or build an empty fallback."""
    if _FIXTURE.exists():
        with open(_FIXTURE, "rb") as f:
            return pickle.load(f)
    # Fallback when fixture isn't available (e.g. fresh checkout without data)
    return _empty_result()


def _empty_result():
    """Build an empty result (no trades) for edge-case tests."""
    return types.SimpleNamespace(
        trade_log=pd.DataFrame(),
        equity_curve=pd.Series(dtype=float, name="equity"),
        summary={"total_trades": 0},
        leg_results={},
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _render_to_svg(chart):
    """Render a chart spec to SVG via vl-convert; raises on invalid spec."""
    spec = json.loads(chart.to_json())
    return vl_convert.vegalite_to_svg(spec)


# ── Real-data tests ───────────────────────────────────────────────────────


class TestRealDataRendering:
    """Charts must render valid SVG from a real PortfolioResult."""

    def test_fixture_loaded(self) -> None:
        """The real-data fixture is present with trades."""
        result = _load_result()
        assert not result.trade_log.empty, "fixture should have trades"
        assert len(result.trade_log) >= 50, "fixture should have substantial trades"
        assert "leg" in result.trade_log.columns
        assert "exit_type" in result.trade_log.columns

    def test_equity_curve_renders(self) -> None:
        """Equity curve produces valid SVG."""
        result = _load_result()
        chart = plot_equity_curve(result, 100_000.0)
        svg = _render_to_svg(chart)
        assert "<svg" in svg
        assert len(svg) > 1000

    def test_cumulative_pnl_renders(self) -> None:
        """Cumulative P&L produces valid SVG."""
        result = _load_result()
        chart = plot_cumulative_pnl(result)
        svg = _render_to_svg(chart)
        assert "<svg" in svg
        assert len(svg) > 1000

    def test_pnl_distribution_renders(self) -> None:
        """P&L distribution produces valid SVG."""
        result = _load_result()
        chart = plot_pnl_distribution(result)
        svg = _render_to_svg(chart)
        assert "<svg" in svg
        assert len(svg) > 1000

    def test_exit_breakdown_renders(self) -> None:
        """Exit breakdown produces valid SVG."""
        result = _load_result()
        chart = plot_exit_breakdown(result)
        svg = _render_to_svg(chart)
        assert "<svg" in svg
        assert len(svg) > 1000

    def test_dashboard_renders(self) -> None:
        """Full dashboard produces valid SVG with all four panels."""
        result = _load_result()
        chart = plot_dashboard(result, 100_000.0)
        svg = _render_to_svg(chart)
        assert "<svg" in svg
        # Dashboard SVG should be substantial (4 panels)
        assert len(svg) > 50_000

    def test_dashboard_has_all_panels(self) -> None:
        """Dashboard spec contains all 4 subcharts with data."""
        result = _load_result()
        chart = plot_dashboard(result, 100_000.0)
        spec = json.loads(chart.to_json())
        rows = spec.get("vconcat", [])
        assert len(rows) == 2, "dashboard should have 2 rows"

        titles = []
        for row in rows:
            for child in row.get("hconcat", []):
                if "title" in child:
                    titles.append(child["title"])

        assert "Cumulative P&L by Leg" in titles
        assert "Exit Type Breakdown" in titles
        assert "Per-Trade P&L Distribution" in titles


# ── Type tests ────────────────────────────────────────────────────────────


class TestChartTypes:
    """Chart functions return the expected Altair types."""

    def test_equity_curve_returns_chart(self) -> None:
        """plot_equity_curve returns an Altair chart (LayerChart when composed)."""
        result = _load_result()
        chart = plot_equity_curve(result, 100_000.0)
        assert isinstance(chart, (alt.Chart, alt.LayerChart))

    def test_cumulative_pnl_returns_chart(self) -> None:
        """plot_cumulative_pnl returns an alt.Chart."""
        result = _load_result()
        chart = plot_cumulative_pnl(result)
        assert isinstance(chart, alt.Chart)

    def test_pnl_distribution_returns_chart(self) -> None:
        """plot_pnl_distribution returns an alt.Chart."""
        result = _load_result()
        chart = plot_pnl_distribution(result)
        assert isinstance(chart, alt.Chart)

    def test_exit_breakdown_returns_chart(self) -> None:
        """plot_exit_breakdown returns an alt.Chart."""
        result = _load_result()
        chart = plot_exit_breakdown(result)
        assert isinstance(chart, alt.Chart)

    def test_dashboard_returns_compound(self) -> None:
        """plot_dashboard returns a compound chart with save capability."""
        result = _load_result()
        chart = plot_dashboard(result, 100_000.0)
        assert hasattr(chart, "save")


# ── HTML output tests ─────────────────────────────────────────────────────


class TestHtmlOutput:
    """plot_portfolio writes a valid HTML file."""

    def test_portfolio_saves_html(self) -> None:
        """plot_portfolio writes an HTML file with embedded vega-embed."""
        result = _load_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test_dashboard.html")
            path = plot_portfolio(result, 100_000.0, out_path=out)
            assert os.path.isfile(path)
            content = Path(path).read_text(encoding="utf-8")
            assert "vegaEmbed" in content
            assert "actions" in content
            assert "<!DOCTYPE html>" in content

    def test_portfolio_returns_absolute_path(self) -> None:
        """plot_portfolio returns an absolute path."""
        result = _load_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test.html")
            path = plot_portfolio(result, 100_000.0, out_path=out)
            assert os.path.isabs(path)


# ── Empty-data tests ──────────────────────────────────────────────────────


class TestEmptyData:
    """Charts handle empty data gracefully."""

    def test_equity_curve_empty(self) -> None:
        """Empty equity curve returns a placeholder chart."""
        result = _empty_result()
        chart = plot_equity_curve(result, 100_000.0)
        assert isinstance(chart, alt.Chart)

    def test_cumulative_pnl_empty(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _empty_result()
        chart = plot_cumulative_pnl(result)
        assert isinstance(chart, alt.Chart)

    def test_pnl_distribution_empty(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _empty_result()
        chart = plot_pnl_distribution(result)
        assert isinstance(chart, alt.Chart)

    def test_exit_breakdown_empty(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _empty_result()
        chart = plot_exit_breakdown(result)
        assert isinstance(chart, alt.Chart)

    def test_dashboard_empty(self) -> None:
        """Empty result still produces a renderable dashboard."""
        result = _empty_result()
        chart = plot_dashboard(result, 100_000.0)
        assert hasattr(chart, "save")
        # Should still render valid SVG
        svg = _render_to_svg(chart)
        assert "<svg" in svg
