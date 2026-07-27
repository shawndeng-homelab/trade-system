"""Tests for backtest_charts: verify chart functions work with synthetic data."""

import os
import tempfile
import types
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
from backtest_charts import plot_cumulative_pnl
from backtest_charts import plot_dashboard
from backtest_charts import plot_equity_curve
from backtest_charts import plot_exit_breakdown
from backtest_charts import plot_pnl_distribution
from backtest_charts import plot_portfolio


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_trade_log(n: int = 10) -> pd.DataFrame:
    """Build a synthetic trade log matching optopsy schema."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-15", periods=n, freq="7D")
    pnl = np.random.normal(500, 300, n)
    return pd.DataFrame(
        {
            "trade_id": range(1, n + 1),
            "underlying_symbol": "TEST",
            "entry_date": dates - pd.Timedelta(days=7),
            "exit_date": dates,
            "days_held": 7,
            "expiration": dates + pd.Timedelta(days=30),
            "entry_cost": -5.0,
            "exit_proceeds": -5.0 + pnl / 100,
            "quantity": 1,
            "multiplier": 100,
            "dollar_cost": 500.0,
            "dollar_proceeds": 500.0 + pnl,
            "realized_pnl": pnl,
            "pct_change": pnl / 500,
            "cumulative_pnl": pnl.cumsum(),
            "equity": 100_000 + pnl.cumsum(),
            "description": "c 100.0",
            "exit_type": np.random.choice(["take_profit", "expiration", "stop_loss"], n),
            "leg": np.random.choice(["leaps", "short_call"], n),
        }
    )


def _make_equity_curve(trade_log: pd.DataFrame) -> pd.Series:
    """Build an equity curve from a trade log."""
    s = trade_log.set_index("exit_date")["equity"]
    s.index = pd.to_datetime(s.index)
    s.name = "equity"
    return s


def _make_result(n: int = 10) -> types.SimpleNamespace:
    """Build a synthetic PortfolioResult-like object."""
    tl = _make_trade_log(n)
    ec = _make_equity_curve(tl)
    summary = {
        "total_trades": n,
        "winning_trades": int((tl["realized_pnl"] > 0).sum()),
        "losing_trades": int((tl["realized_pnl"] < 0).sum()),
        "win_rate": float((tl["realized_pnl"] > 0).mean()),
        "total_pnl": float(tl["realized_pnl"].sum()),
        "total_return": float(tl["realized_pnl"].sum()) / 100_000,
        "avg_pnl": float(tl["realized_pnl"].mean()),
        "avg_win": float(tl.loc[tl["realized_pnl"] > 0, "realized_pnl"].mean()),
        "avg_loss": float(tl.loc[tl["realized_pnl"] < 0, "realized_pnl"].mean()),
        "max_win": float(tl["realized_pnl"].max()),
        "max_loss": float(tl["realized_pnl"].min()),
        "profit_factor": 1.5,
        "max_drawdown": 0.05,
        "avg_days_in_trade": 7.0,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.8,
        "var_95": -200,
        "cvar_95": -350,
        "calmar_ratio": 0.8,
        "omega_ratio": 1.1,
        "tail_ratio": 0.9,
    }
    return types.SimpleNamespace(
        trade_log=tl,
        equity_curve=ec,
        summary=summary,
        leg_results={},
    )


def _make_empty_result() -> types.SimpleNamespace:
    """Build an empty result (no trades)."""
    return types.SimpleNamespace(
        trade_log=pd.DataFrame(),
        equity_curve=pd.Series(dtype=float, name="equity"),
        summary={"total_trades": 0},
        leg_results={},
    )


# ── Tests ────────────────────────────────────────────────────────────────


class TestEquityCurve:
    """Tests for plot_equity_curve."""

    def test_returns_chart(self) -> None:
        """plot_equity_curve returns an Altair chart (LayerChart when composed)."""
        result = _make_result()
        chart = plot_equity_curve(result, 100_000.0)
        assert isinstance(chart, (alt.Chart, alt.LayerChart))

    def test_empty_data(self) -> None:
        """Empty equity curve returns a placeholder chart."""
        result = _make_empty_result()
        chart = plot_equity_curve(result, 100_000.0)
        assert isinstance(chart, alt.Chart)


class TestCumulativePnl:
    """Tests for plot_cumulative_pnl."""

    def test_returns_chart(self) -> None:
        """plot_cumulative_pnl returns an alt.Chart."""
        result = _make_result()
        chart = plot_cumulative_pnl(result)
        assert isinstance(chart, alt.Chart)

    def test_empty_data(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _make_empty_result()
        chart = plot_cumulative_pnl(result)
        assert isinstance(chart, alt.Chart)


class TestPnlDistribution:
    """Tests for plot_pnl_distribution."""

    def test_returns_chart(self) -> None:
        """plot_pnl_distribution returns an alt.Chart."""
        result = _make_result()
        chart = plot_pnl_distribution(result)
        assert isinstance(chart, alt.Chart)

    def test_empty_data(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _make_empty_result()
        chart = plot_pnl_distribution(result)
        assert isinstance(chart, alt.Chart)


class TestExitBreakdown:
    """Tests for plot_exit_breakdown."""

    def test_returns_chart(self) -> None:
        """plot_exit_breakdown returns an alt.Chart."""
        result = _make_result()
        chart = plot_exit_breakdown(result)
        assert isinstance(chart, alt.Chart)

    def test_empty_data(self) -> None:
        """Empty trade log returns a placeholder chart."""
        result = _make_empty_result()
        chart = plot_exit_breakdown(result)
        assert isinstance(chart, alt.Chart)


class TestDashboard:
    """Tests for plot_dashboard and plot_portfolio."""

    def test_dashboard_returns_vconcat(self) -> None:
        """plot_dashboard returns a compound chart."""
        result = _make_result()
        chart = plot_dashboard(result, 100_000.0)
        # Altair compound charts are TopLevelMixin subclasses
        assert hasattr(chart, "save")

    def test_portfolio_saves_html(self) -> None:
        """plot_portfolio writes an HTML file and returns its path."""
        result = _make_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "test_dashboard.html")
            path = plot_portfolio(result, 100_000.0, out_path=out)
            assert os.path.isfile(path)
            content = Path(path).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content or "vega-embed" in content

    def test_empty_data(self) -> None:
        """Empty result still produces a dashboard."""
        result = _make_empty_result()
        chart = plot_dashboard(result, 100_000.0)
        assert hasattr(chart, "save")
