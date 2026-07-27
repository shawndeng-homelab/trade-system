"""Dashboard: combine individual charts into a multi-panel layout."""

import json
import os

import altair as alt

from backtest_charts.equity import plot_equity_curve
from backtest_charts.exits import plot_exit_breakdown
from backtest_charts.pnl import plot_cumulative_pnl
from backtest_charts.pnl import plot_pnl_distribution


# HTML template for saved dashboards. The ``#vis`` container is given an
# explicit width so that ``width='container'`` subcharts (which need a
# parent with an independently-defined size) render full-width instead of
# collapsing into a narrow strip.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@7"></script>
  <style>
    body {{
      margin: 0;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    #vis {{
      width: 100%;
      max-width: 1600px;
      margin: 0 auto;
    }}
  </style>
</head>
<body>
  <div id="vis"></div>
  <script type="text/javascript">
    var spec = {spec};
    var opt = {{"renderer": "canvas", "actions": true}};
    vegaEmbed("#vis", spec, opt);
  </script>
</body>
</html>
"""


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
    spec = json.loads(chart.to_json())
    html = _HTML_TEMPLATE.format(spec=json.dumps(spec, indent=None))
    with open(out_abs, "w", encoding="utf-8") as f:
        f.write(html)
    return out_abs
