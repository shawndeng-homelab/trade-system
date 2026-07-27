"""Dashboard: combine individual charts into a multi-panel layout."""

import os

import altair as alt

from backtest_charts.equity import plot_equity_curve
from backtest_charts.exits import plot_exit_breakdown
from backtest_charts.pnl import plot_cumulative_pnl
from backtest_charts.pnl import plot_pnl_distribution


def plot_dashboard(result, initial_capital: float) -> alt.VConcatChart:
    """Build a 2×2 dashboard from backtest results.

    Layout::

        ┌─────────────────────┬──────────────────────┐
        │  Equity Curve       │  Cumulative P&L      │
        ├─────────────────────┼──────────────────────┤
        │  P&L Distribution   │  Exit Type Breakdown │
        └─────────────────────┴──────────────────────┘

    Args:
        result: Object with ``trade_log``, ``equity_curve``, ``summary``,
            and ``leg_results`` attributes (e.g. ``optopsy.PortfolioResult``).
        initial_capital: Starting capital for the equity-curve reference line.

    Returns:
        Compound Altair chart that renders in Jupyter or can be saved via
        ``chart.save(path)``.
    """
    equity = plot_equity_curve(result, initial_capital)
    cum_pnl = plot_cumulative_pnl(result)
    pnl_dist = plot_pnl_distribution(result)
    exits = plot_exit_breakdown(result)

    top = alt.hconcat(equity, cum_pnl)
    bottom = alt.hconcat(pnl_dist, exits)

    return alt.vconcat(top, bottom).properties(
        title="PMCC Backtest Dashboard",
        padding=10,
    )


def plot_portfolio(
    result,
    initial_capital: float,
    out_path: str = "pmcc_dashboard.html",
) -> str:
    """Render the backtest dashboard and save to HTML.

    Convenience wrapper around :func:`plot_dashboard` that also writes
    the chart to an HTML file.

    Args:
        result: Backtest result object (see :func:`plot_dashboard`).
        initial_capital: Starting capital for the equity-curve reference line.
        out_path: Output HTML file path.

    Returns:
        The absolute path to the written HTML file.
    """
    chart = plot_dashboard(result, initial_capital)
    out_abs = os.path.abspath(out_path)
    chart.save(out_abs)
    return out_abs
