"""BacktestReport: object-oriented API for backtest chart rendering.

Wraps a backtest result, pre-extracts validated data, and provides
methods for individual charts, dashboard composition, and custom
panel registration.
"""

import os
import typing
from collections import OrderedDict

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest_charts._util import DEFAULT_CAPITAL
from backtest_charts._util import PANEL_HEIGHT
from backtest_charts.data import BacktestData
from backtest_charts.equity import plot_equity
from backtest_charts.exits import plot_exits
from backtest_charts.pnl import plot_cum_pnl
from backtest_charts.pnl import plot_pnl_dist
from backtest_charts.summary import plot_summary


# Type alias for panel factory functions
PanelFactory = typing.Callable[[BacktestData], go.Figure]

# Class-level default panel registry (shared across instances)
DEFAULT_PANELS: OrderedDict[str, PanelFactory] = OrderedDict(
    [
        ("equity_curve", plot_equity),
        ("cumulative_pnl", plot_cum_pnl),
        ("pnl_distribution", plot_pnl_dist),
        ("exit_breakdown", plot_exits),
        ("summary", plot_summary),
    ]
)


def _is_domain_figure(fig: go.Figure) -> bool:
    """Return True if the figure contains traces requiring a domain subplot (e.g. Table)."""
    return any(isinstance(tr, go.Table) for tr in fig.data)


def _propagate_layout(dash: go.Figure, panel_fig: go.Figure, row: int, col: int) -> None:
    """Copy per-panel axis formatting and shapes into the correct subplot cell.

    Args:
        dash: The subplot figure to update.
        panel_fig: The standalone panel figure to read layout from.
        row: Subplot row (1-based).
        col: Subplot column (1-based).
    """
    ya = panel_fig.layout.yaxis
    xa = panel_fig.layout.xaxis

    # Y-axis formatting
    if ya.tickformat:
        dash.update_yaxes(tickformat=ya.tickformat, row=row, col=col)
    if ya.zeroline is False:
        dash.update_yaxes(zeroline=False, row=row, col=col)
    if ya.title and ya.title.text:
        dash.update_yaxes(title_text=ya.title.text, row=row, col=col)

    # X-axis formatting
    if xa.title and xa.title.text:
        dash.update_xaxes(title_text=xa.title.text, row=row, col=col)
    if xa.tickformat:
        dash.update_xaxes(tickformat=xa.tickformat, row=row, col=col)

    # Shapes (e.g. hlines from equity curve)
    for shape in panel_fig.layout.shapes or []:
        dash.add_shape(shape, row=row, col=col)

    # Annotations (e.g. hline labels from equity curve)
    for ann in panel_fig.layout.annotations or []:
        dash.add_annotation(ann, row=row, col=col)


class BacktestReport:
    """Object-oriented API for backtest chart rendering.

    Wraps a backtest result object, pre-extracts validated data, and
    provides methods for individual charts, dashboard composition,
    and custom panel registration.

    Usage::

        from backtest_charts import BacktestReport

        report = BacktestReport(result, capital=100_000)
        report.plot_equity()       # go.Figure
        report.plot_dashboard()    # go.Figure
        report.save_html()         # writes file

    Custom panels::

        @report.panel("my_chart")
        def my_chart(data: BacktestData) -> go.Figure:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=data.trade_log["exit_type"], ...))
            return fig
    """

    def __init__(self, result, capital: float = DEFAULT_CAPITAL, *, title: str = "Backtest Dashboard") -> None:
        """Create a BacktestReport from a backtest result.

        Args:
            result: Backtest result object (duck-typed).
            capital: Initial capital for reference lines.
            title: Dashboard title (shown in the dashboard header).
        """
        self._data = BacktestData.from_result(result, capital)
        self._panels: OrderedDict[str, PanelFactory] = OrderedDict(DEFAULT_PANELS)
        self._title = title

    @property
    def data(self) -> BacktestData:
        """Access pre-extracted backtest data for custom panels."""
        return self._data

    @property
    def capital(self) -> float:
        """Initial capital."""
        return self._data.capital

    # ── Built-in chart methods ────────────────────────────────────────

    def plot_equity(self) -> go.Figure:
        """Plot portfolio equity curve with a starting-capital reference line."""
        return plot_equity(self._data)

    def plot_cum_pnl(self) -> go.Figure:
        """Plot cumulative realized P&L by leg."""
        return plot_cum_pnl(self._data)

    def plot_pnl_dist(self) -> go.Figure:
        """Plot per-trade realized P&L distribution."""
        return plot_pnl_dist(self._data)

    def plot_exits(self) -> go.Figure:
        """Plot exit-type count grouped by leg."""
        return plot_exits(self._data)

    def plot_summary(self) -> go.Figure:
        """Plot strategy summary metrics as a table."""
        return plot_summary(self._data)

    # ── Dashboard ─────────────────────────────────────────────────────

    def plot_dashboard(self, *, columns: int = 2) -> go.Figure:
        """Build a multi-panel dashboard from backtest results.

        Layout (default 2-column grid)::

            ┌─────────────────────┬──────────────────────┐
            │  Equity Curve       │  Cumulative P&L      │
            ├─────────────────────┼──────────────────────┤
            │  P&L Distribution   │  Exit Type Breakdown │
            ├─────────────────────┼──────────────────────┤
            │  Strategy Summary                           │
            └─────────────────────────────────────────────┘

        Panels are sourced from the instance panel registry.
        Add custom panels via :meth:`panel` or :meth:`add_panel`,
        or remove defaults via :meth:`remove_panel`.

        Args:
            columns: Number of columns in the grid layout (default 2).

        Returns:
            Plotly figure with subplots.
        """
        # Build panels and detect subplot types in a single pass
        panel_data: list[tuple[str, go.Figure, bool]] = []
        for key, factory in self._panels.items():
            fig = factory(self._data)
            panel_data.append((key, fig, _is_domain_figure(fig)))

        n = len(panel_data)
        rows = (n + columns - 1) // columns

        # Build specs grid and subplot titles in one pass
        specs: list[list[dict[str, str] | None]] = []
        subplot_titles: list[str] = []
        for r in range(rows):
            row_specs: list[dict[str, str] | None] = []
            for c in range(columns):
                idx = r * columns + c
                if idx < n:
                    _key, fig, is_domain = panel_data[idx]
                    row_specs.append({"type": "domain"} if is_domain else {})
                    title_text = fig.layout.title.text if fig.layout.title else ""
                    subplot_titles.append(title_text or "")
                else:
                    row_specs.append(None)
            specs.append(row_specs)

        dash = make_subplots(
            rows=rows,
            cols=columns,
            specs=specs,
            subplot_titles=subplot_titles,
        )

        for i, (_key, panel_fig, is_domain) in enumerate(panel_data):
            row = (i // columns) + 1
            col = (i % columns) + 1
            for trace in panel_fig.data:
                dash.add_trace(trace, row=row, col=col)
            if not is_domain:
                _propagate_layout(dash, panel_fig, row, col)

        dash.update_layout(
            title={"text": self._title, "x": 0.5},
            height=PANEL_HEIGHT * rows + 80,
        )
        return dash

    def save_html(self, path: str = "backtest_dashboard.html") -> str:
        """Render the dashboard and save to HTML.

        Args:
            path: Output HTML file path.

        Returns:
            The absolute path to the written HTML file.
        """
        fig = self.plot_dashboard()
        out_abs = os.path.abspath(path)
        fig.write_html(out_abs, include_plotlyjs="cdn")
        return out_abs

    # ── Panel extension ───────────────────────────────────────────────

    def panel(self, key: str):
        """Decorator to register a custom panel factory.

        Usage::

            @report.panel("my_chart")
            def my_chart(data: BacktestData) -> go.Figure:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=data.trade_log["exit_type"], ...))
                return fig

        Args:
            key: Unique panel identifier.

        Returns:
            Decorator that registers the function and returns it unchanged.
        """

        def decorator(fn: PanelFactory) -> PanelFactory:
            self._panels[key] = fn
            return fn

        return decorator

    def add_panel(self, key: str, factory: PanelFactory) -> None:
        """Register a custom panel factory.

        Args:
            key: Unique panel identifier.
            factory: Callable ``(BacktestData) -> go.Figure``.
        """
        self._panels[key] = factory

    def remove_panel(self, key: str) -> None:
        """Remove a panel from the registry.

        Args:
            key: Panel identifier to remove.
        """
        self._panels.pop(key, None)

    def list_panels(self) -> list[str]:
        """Return the ordered list of registered panel keys."""
        return list(self._panels.keys())
