"""Portfolio equity curve visualization."""

import pandas as pd
import plotly.graph_objects as go

from backtest_charts._util import _apply_chart_layout
from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


_TITLE = "Portfolio Equity Curve"


def plot_equity(data: BacktestData) -> go.Figure:
    """Plot portfolio equity curve with a starting-capital reference line.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly line chart of portfolio equity over time.
    """
    if not data.has_equity:
        return _empty_chart(_TITLE, "No equity curve data")

    df = pd.DataFrame(
        {
            "date": data.equity_curve.index,
            "equity": data.equity_curve.values,
        }
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["equity"],
            mode="lines",
            line={"color": "indigo", "width": 2},
            name="Equity",
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Equity: $%{y:,.0f}<extra></extra>",
        )
    )

    # Reference line at initial capital
    fig.add_hline(
        y=data.capital,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"Start ${data.capital:,.0f}",
        annotation_position="top left",
        annotation_font_size=10,
        annotation_font_color="gray",
    )

    _apply_chart_layout(fig, _TITLE)
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Equity ($)",
        yaxis_tickformat="$,.0f",
        yaxis_zeroline=False,
    )
    return fig


# Backward-compatible wrapper
def plot_equity_curve(result, initial_capital: float) -> go.Figure:
    """Plot portfolio equity curve (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_equity` instead.
    """
    return plot_equity(BacktestData.from_result(result, initial_capital))
