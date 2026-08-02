"""P&L visualizations: cumulative P&L by leg and per-trade distribution."""

import plotly.graph_objects as go

from backtest_charts._util import DEFAULT_CAPITAL
from backtest_charts._util import _apply_chart_layout
from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


_CUM_PNL_TITLE = "Cumulative P&L by Leg"
_PNL_DIST_TITLE = "Per-Trade P&L Distribution"


def plot_cum_pnl(data: BacktestData) -> go.Figure:
    """Plot cumulative realized P&L by leg.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly multi-line chart of cumulative P&L per leg over time.
    """
    log = data.trade_log
    if not data.has_trades or "leg" not in log.columns:
        return _empty_chart(_CUM_PNL_TITLE, "No trade log data")

    fig = go.Figure()
    for leg_name in log["leg"].unique():
        leg_log = log[log["leg"] == leg_name].sort_values("exit_date")
        cum_pnl = leg_log["realized_pnl"].cumsum()
        fig.add_trace(
            go.Scatter(
                x=leg_log["exit_date"],
                y=cum_pnl,
                mode="lines",
                line={"width": 2},
                name=str(leg_name),
                hovertemplate="Leg: %{data.name}<br>Date: %{x|%Y-%m-%d}<br>Cum P&L: $%{y:,.0f}<extra></extra>",
            )
        )

    _apply_chart_layout(fig, _CUM_PNL_TITLE)
    fig.update_layout(
        xaxis_title="Exit date",
        yaxis_title="Cumulative P&L ($)",
        yaxis_tickformat="$,.0f",
    )
    return fig


def plot_pnl_dist(data: BacktestData) -> go.Figure:
    """Plot per-trade realized P&L as a bar chart.

    Positive P&L bars are green, negative are crimson.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly bar chart of per-trade P&L.
    """
    log = data.trade_log
    if not data.has_trades or "realized_pnl" not in log.columns:
        return _empty_chart(_PNL_DIST_TITLE, "No trade log data")

    trade_ids = log["trade_id"] if "trade_id" in log.columns else range(1, len(log) + 1)
    colors = ["green" if v >= 0 else "crimson" for v in log["realized_pnl"]]

    # Build hover text from available columns
    customdata_cols = [c for c in ("exit_type", "leg") if c in log.columns]
    customdata = log[customdata_cols].values if customdata_cols else None

    hovertemplate_parts = ["Trade #: %{x}", "P&L: $%{y:,.0f}"]
    if "exit_type" in customdata_cols:
        idx = customdata_cols.index("exit_type")
        hovertemplate_parts.append(f"Exit type: %{{customdata[{idx}]}}")
    if "leg" in customdata_cols:
        idx = customdata_cols.index("leg")
        hovertemplate_parts.append(f"Leg: %{{customdata[{idx}]}}")
    hovertemplate_parts.append("<extra></extra>")
    hovertemplate = "<br>".join(hovertemplate_parts)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=trade_ids,
            y=log["realized_pnl"],
            marker_color=colors,
            showlegend=False,
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    )

    _apply_chart_layout(fig, _PNL_DIST_TITLE)
    fig.update_layout(
        xaxis_title="Trade #",
        yaxis_title="P&L ($)",
        yaxis_tickformat="$,.0f",
        bargap=0.1,
    )
    return fig


# Backward-compatible wrappers
def plot_cumulative_pnl(result) -> go.Figure:
    """Plot cumulative P&L by leg (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_cum_pnl` instead.
    """
    return plot_cum_pnl(BacktestData.from_result(result, capital=DEFAULT_CAPITAL))


def plot_pnl_distribution(result) -> go.Figure:
    """Plot per-trade P&L distribution (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_pnl_dist` instead.
    """
    return plot_pnl_dist(BacktestData.from_result(result, capital=DEFAULT_CAPITAL))
