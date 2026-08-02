"""Shared helpers for backtest-charts modules."""

import plotly.graph_objects as go


def _empty_chart(title: str, message: str) -> go.Figure:
    """Return a figure that displays a placeholder message when data is missing.

    Args:
        title: Chart title.
        message: Placeholder text to display.

    Returns:
        A ``go.Figure`` with hidden axes and a centered gray annotation.
    """
    fig = go.Figure()
    fig.update_layout(
        title={"text": title, "x": 0.5},
        xaxis={"visible": False},
        yaxis={"visible": False},
        width=580,
        height=280,
        annotations=[
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 14, "color": "gray"},
            }
        ],
    )
    return fig
