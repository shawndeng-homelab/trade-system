"""Shared helpers for backtest-charts modules."""

import plotly.graph_objects as go


# Default panel dimensions — used as fallback only; charts are responsive by default
PANEL_WIDTH = None
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
    height: int | None = PANEL_HEIGHT,
    width: int | None = None,
) -> go.Figure:
    """Apply standard chart layout (centered title, responsive sizing).

    By default charts are responsive — no fixed ``width`` so they fill
    their container (notebook cell, browser window, etc.).  ``height``
    defaults to 280px but can be overridden per-chart.

    Args:
        fig: The figure to update.
        title: Chart title string.
        height: Panel height in pixels (default 280).  Set ``None`` for
            fully responsive height.
        width: Panel width in pixels.  Defaults to ``None`` (responsive).

    Returns:
        The same figure, updated in-place.
    """
    layout = {"title": {"text": title, "x": 0.5}, "autosize": True}
    if height is not None:
        layout["height"] = height
    if width is not None:
        layout["width"] = width
    fig.update_layout(**layout)
    return fig
