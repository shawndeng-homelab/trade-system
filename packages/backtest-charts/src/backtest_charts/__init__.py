"""Altair visualizations for optopsy backtest results.

Provides individual chart functions that return ``alt.Chart`` objects
(composable in Jupyter) and a ``plot_portfolio`` convenience function
that saves a full dashboard to HTML.

Quick start::

    from backtest_charts import plot_portfolio

    result = run_pmcc(options, stock, config)
    path = plot_portfolio(result, config.capital)
"""

from backtest_charts.dashboard import plot_dashboard
from backtest_charts.dashboard import plot_portfolio
from backtest_charts.equity import plot_equity_curve
from backtest_charts.exits import plot_exit_breakdown
from backtest_charts.pnl import plot_cumulative_pnl
from backtest_charts.pnl import plot_pnl_distribution


__all__ = [
    "plot_cumulative_pnl",
    "plot_dashboard",
    "plot_equity_curve",
    "plot_exit_breakdown",
    "plot_pnl_distribution",
    "plot_portfolio",
]
