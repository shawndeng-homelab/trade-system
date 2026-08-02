"""P&L visualizations: cumulative P&L by leg and per-trade distribution."""

import pandas as pd
import plotly.graph_objects as go

from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


def plot_cum_pnl(data: BacktestData) -> go.Figure:
    """Plot cumulative realized P&L by leg.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly multi-line chart of cumulative P&L per leg over time.
    """
    log = data.trade_log
    if not data.has_trades or "leg" not in log.columns:
        return _empty_chart("Cumulative P&L by Leg", "No trade log data")

    rows = []
    for leg_name in log["leg"].unique():
        leg_log = log[log["leg"] == leg_name].sort_values("exit_date").copy()
        leg_log["cumulative_pnl"] = leg_log["realized_pnl"].cumsum()
        leg_log["leg"] = leg_name
        rows.append(leg_log[["exit_date", "cumulative_pnl", "leg"]])

    df = pd.concat(rows, ignore_index=True)

    fig = go.Figure()
    for leg_name in df["leg"].unique():
        leg_df = df[df["leg"] == leg_name]
        fig.add_trace(
            go.Scatter(
                x=leg_df["exit_date"],
                y=leg_df["cumulative_pnl"],
                mode="lines",
                line={"width": 2},
                name=str(leg_name),
                hovertemplate="Leg: %{data.name}<br>Date: %{x|%Y-%m-%d}<br>Cum P&L: $%{y:,.0f}<extra></extra>",
            )
        )

    fig.update_layout(
        title={"text": "Cumulative P&L by Leg", "x": 0.5},
        xaxis_title="Exit date",
        yaxis_title="Cumulative P&L ($)",
        yaxis_tickformat="$,.0f",
        width=580,
        height=280,
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
        return _empty_chart("Per-Trade P&L Distribution", "No trade log data")

    df = log.copy()
    if "trade_id" not in df.columns:
        df["trade_id"] = range(1, len(df) + 1)

    colors = ["green" if v >= 0 else "crimson" for v in df["realized_pnl"]]

    # Build hover text from available columns
    customdata_cols = [c for c in ("exit_type", "leg") if c in df.columns]
    customdata = df[customdata_cols].values if customdata_cols else None

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
            x=df["trade_id"],
            y=df["realized_pnl"],
            marker_color=colors,
            showlegend=False,
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    )

    fig.update_layout(
        title={"text": "Per-Trade P&L Distribution", "x": 0.5},
        xaxis_title="Trade #",
        yaxis_title="P&L ($)",
        yaxis_tickformat="$,.0f",
        width=580,
        height=280,
        bargap=0.1,
    )
    return fig


# Backward-compatible wrappers
def plot_cumulative_pnl(result) -> go.Figure:
    """Plot cumulative P&L by leg (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_cum_pnl` instead.
    """
    return plot_cum_pnl(BacktestData.from_result(result, capital=100_000.0))


def plot_pnl_distribution(result) -> go.Figure:
    """Plot per-trade P&L distribution (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_pnl_dist` instead.
    """
    return plot_pnl_dist(BacktestData.from_result(result, capital=100_000.0))
