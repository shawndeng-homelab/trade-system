"""Plotly visualizations for optopsy backtest results.

New API (recommended)::

    from backtest_charts import BacktestReport

    report = BacktestReport(result, capital=100_000)
    report.plot_equity()       # go.Figure
    report.plot_dashboard()    # go.Figure
    report.save_html()         # writes file

    # Custom panels
    @report.panel("my_chart")
    def my_chart(data: BacktestData) -> go.Figure:
        ...

Legacy API (deprecated)::

    from backtest_charts import plot_equity_curve
    fig = plot_equity_curve(result, 100_000)
"""

import typing
import warnings

import plotly.graph_objects as go

from backtest_charts._util import DEFAULT_CAPITAL
from backtest_charts.data import BacktestData
from backtest_charts.report import BacktestReport


# ── New API ───────────────────────────────────────────────────────────

__all__ = [
    # Backward compat (deprecated)
    "PANEL_REGISTRY",
    "BacktestData",
    "BacktestReport",
    "plot_cumulative_pnl",
    "plot_dashboard",
    "plot_equity_curve",
    "plot_exit_breakdown",
    "plot_pnl_distribution",
    "plot_portfolio",
]


# ── Backward-compatible function wrappers ─────────────────────────────


def plot_equity_curve(result, initial_capital: float) -> go.Figure:
    """Plot equity curve (legacy). Use ``BacktestReport.plot_equity()`` instead."""
    warnings.warn(
        "plot_equity_curve() is deprecated; use BacktestReport.plot_equity()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result, capital=initial_capital).plot_equity()


def plot_cumulative_pnl(result) -> go.Figure:
    """Plot cumulative P&L (legacy). Use ``BacktestReport.plot_cum_pnl()`` instead."""
    warnings.warn(
        "plot_cumulative_pnl() is deprecated; use BacktestReport.plot_cum_pnl()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result).plot_cum_pnl()


def plot_pnl_distribution(result) -> go.Figure:
    """Plot P&L distribution (legacy). Use ``BacktestReport.plot_pnl_dist()`` instead."""
    warnings.warn(
        "plot_pnl_distribution() is deprecated; use BacktestReport.plot_pnl_dist()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result).plot_pnl_dist()


def plot_exit_breakdown(result) -> go.Figure:
    """Plot exit breakdown (legacy). Use ``BacktestReport.plot_exits()`` instead."""
    warnings.warn(
        "plot_exit_breakdown() is deprecated; use BacktestReport.plot_exits()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result).plot_exits()


def plot_dashboard(result, initial_capital: float, *, columns: int = 2) -> go.Figure:
    """Plot dashboard (legacy). Use ``BacktestReport.plot_dashboard()`` instead."""
    warnings.warn(
        "plot_dashboard() is deprecated; use BacktestReport.plot_dashboard()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result, capital=initial_capital).plot_dashboard(columns=columns)


def plot_portfolio(result, initial_capital: float, out_path: str = "backtest_dashboard.html") -> str:
    """Save dashboard HTML (legacy). Use ``BacktestReport.save_html()`` instead."""
    warnings.warn(
        "plot_portfolio() is deprecated; use BacktestReport.save_html()",
        DeprecationWarning,
        stacklevel=2,
    )
    return BacktestReport(result, capital=initial_capital).save_html(path=out_path)


# ── Backward-compatible PANEL_REGISTRY ────────────────────────────────


class _CompatPanelRegistry:
    """Shim that delegates to BacktestReport's class-level DEFAULT_PANELS.

    Mutations affect the ``DEFAULT_PANELS`` class variable, which all
    new ``BacktestReport`` instances copy at construction.

    Note: ``register()`` accepts new-style factories
    ``(BacktestData) -> go.Figure``.  The old-style
    ``(result, **kwargs) -> go.Figure`` signature is no longer supported
    through this shim — use ``BacktestReport.add_panel()`` instead.
    """

    def register(self, key: str, factory: typing.Callable) -> None:
        """Register a panel factory under *key*.

        Args:
            key: Unique identifier.
            factory: Callable ``(BacktestData) -> go.Figure``.
        """
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        DEFAULT_PANELS[key] = factory

    def deregister(self, key: str) -> None:
        """Remove a panel from the registry."""
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        DEFAULT_PANELS.pop(key, None)

    def __contains__(self, key: str) -> bool:
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        return key in DEFAULT_PANELS

    def __getitem__(self, key: str) -> typing.Callable:
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        return DEFAULT_PANELS[key]

    def keys(self) -> list[str]:
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        return list(DEFAULT_PANELS.keys())

    def build(self, result, **kwargs) -> list[go.Figure]:
        """Build all registered panels (old-style)."""
        from backtest_charts.report import DEFAULT_PANELS  # noqa: PLC0415

        data = BacktestData.from_result(result, kwargs.get("initial_capital", DEFAULT_CAPITAL))
        return [factory(data) for factory in DEFAULT_PANELS.values()]


PANEL_REGISTRY = _CompatPanelRegistry()
"""Global panel registry (legacy). Use ``BacktestReport`` instance methods instead."""
