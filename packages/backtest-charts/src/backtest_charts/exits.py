"""Exit-type analysis visualization."""

import plotly.graph_objects as go

from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


def plot_exits(data: BacktestData) -> go.Figure:
    """Plot exit-type count grouped by leg.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly stacked bar chart of exit counts by type, stacked by leg.
    """
    log = data.trade_log
    if not data.has_trades or "exit_type" not in log.columns or "leg" not in log.columns:
        return _empty_chart("Exit Type Breakdown", "No exit type data")

    counts = log.groupby(["leg", "exit_type"]).size().reset_index(name="count")

    fig = go.Figure()
    for leg_name in counts["leg"].unique():
        leg_data = counts[counts["leg"] == leg_name]
        fig.add_trace(
            go.Bar(
                x=leg_data["exit_type"],
                y=leg_data["count"],
                name=str(leg_name),
                hovertemplate="Leg: %{data.name}<br>Exit type: %{x}<br>Count: %{y}<extra></extra>",
            )
        )

    fig.update_layout(
        title={"text": "Exit Type Breakdown", "x": 0.5},
        xaxis_title="Exit type",
        yaxis_title="Count",
        barmode="stack",
        width=580,
        height=280,
    )
    return fig


# Backward-compatible wrapper
def plot_exit_breakdown(result) -> go.Figure:
    """Plot exit-type breakdown (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_exits` instead.
    """
    return plot_exits(BacktestData.from_result(result, capital=100_000.0))
