"""Shared helpers for backtest-charts modules."""

import plotly.graph_objects as go


# Default panel dimensions (single source of truth for all charts + dashboard)
PANEL_WIDTH = 580
PANEL_HEIGHT = 280

# Default capital for legacy wrappers that don't accept a capital parameter
DEFAULT_CAPITAL = 100_000.0


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
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
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


def _apply_chart_layout(
    fig: go.Figure,
    title: str,
    *,
    height: int = PANEL_HEIGHT,
    width: int = PANEL_WIDTH,
) -> go.Figure:
    """Apply standard chart layout (centered title, panel dimensions).

    Args:
        fig: The figure to update.
        title: Chart title string.
        height: Panel height in pixels.
        width: Panel width in pixels.

    Returns:
        The same figure, updated in-place.
    """
    fig.update_layout(
        title={"text": title, "x": 0.5},
        width=width,
        height=height,
    )
    return fig
