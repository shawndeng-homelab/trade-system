"""BacktestReport: object-oriented API for backtest chart rendering.

Wraps a backtest result, pre-extracts validated data, and provides
methods for individual charts, dashboard composition, and custom
panel registration.
"""

import os
import typing
from collections import OrderedDict

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest_charts._util import DEFAULT_CAPITAL
from backtest_charts.comparison import align_benchmarks
from backtest_charts.data import BacktestData
from backtest_charts.data import compute_benchmarks
from backtest_charts.equity import plot_equity
from backtest_charts.evaluation import diagnostic_table
from backtest_charts.evaluation import evaluation_dashboard
from backtest_charts.evaluation import make_evaluation_report
from backtest_charts.evaluation import save_evaluation_html
from backtest_charts.exits import plot_exits
from backtest_charts.pnl import plot_cum_pnl
from backtest_charts.pnl import plot_pnl_dist
from backtest_charts.summary import plot_summary
from backtest_charts.trades import plot_trades


# Type alias for panel factory functions
PanelFactory = typing.Callable[[BacktestData], go.Figure]

# Class-level default panel registry (shared across instances)
DEFAULT_PANELS: OrderedDict[str, PanelFactory] = OrderedDict(
    [
        ("equity_curve", plot_equity),
        ("cumulative_pnl", plot_cum_pnl),
        ("pnl_distribution", plot_pnl_dist),
        ("exit_breakdown", plot_exits),
        ("trade_log", plot_trades),
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
    for axis_name, update in (("xaxis", dash.update_xaxes), ("yaxis", dash.update_yaxes)):
        axis = getattr(panel_fig.layout, axis_name).to_plotly_json()
        # Domain, anchors and axis IDs belong to the destination grid.
        properties = {
            key: axis[key]
            for key in (
                "title",
                "tickformat",
                "ticksuffix",
                "tickprefix",
                "zeroline",
                "visible",
                "showgrid",
                "type",
                "range",
                "autorange",
            )
            if key in axis
        }
        update(**properties, row=row, col=col)

    for shape in panel_fig.layout.shapes or []:
        dash.add_shape(shape, row=row, col=col)
    for ann in panel_fig.layout.annotations or []:
        props = ann.to_plotly_json()
        # Empty-panel messages use paper coordinates in standalone figures.
        # Convert them to coordinates local to the destination subplot.
        if props.get("xref") == "paper":
            props["xref"] = "x domain"
        if props.get("yref") == "paper":
            props["yref"] = "y domain"
        dash.add_annotation(props, row=row, col=col)


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

    def __init__(
        self,
        result,
        capital: float = DEFAULT_CAPITAL,
        *,
        title: str = "Backtest Dashboard",
        benchmark_options: dict[str, "pd.DataFrame"] | None = None,
        stock_data: dict[str, "pd.DataFrame"] | None = None,
        benchmark_results: dict[str, object] | None = None,
        benchmark_capitals: dict[str, float] | None = None,
    ) -> None:
        """Create a BacktestReport from a backtest result.

        Args:
            result: Backtest result object (duck-typed).
            capital: Initial capital for reference lines.
            title: Dashboard title (shown in the dashboard header).
            benchmark_options: Optional mapping of symbol → option chain
                DataFrame used to compute buy-and-hold ATM call benchmarks.
                When provided, the summary table includes return rows for
                each symbol in :data:`~backtest_charts.data.BENCHMARK_SYMBOLS`
                (default SPY, QQQ, IWM).  Each DataFrame must have columns:
                ``quote_date``, ``expiration``, ``option_type``, ``strike``,
                ``bid``, ``ask``, ``delta``.
            stock_data: Optional mapping of symbol → stock OHLCV DataFrame.
                When provided, the equity curve chart overlays each symbol's
                close return on the same percentage axis.  Each DataFrame
                must have columns: ``quote_date``, ``close``.
            benchmark_results: Optional mapping of label → backtest result
                object (duck-typed with ``equity_curve`` attribute).  When
                provided, each result's equity curve is overlaid on the
                equity chart as a dashed line (percentage change from start),
                enabling visual comparison over a common observed interval.
                Full-run trade metrics are omitted when that interval is clipped.
            benchmark_capitals: Optional initial capital per benchmark. Otherwise
                inferred from the trade ledger or final equity and total_return, falling back to the
                first observation with a warning when neither is available.
        """
        self._capital = capital
        self._data = BacktestData.from_result(result, capital)
        self._panels: OrderedDict[str, PanelFactory] = OrderedDict(DEFAULT_PANELS)
        self._title = title

        # Inject stock price data into BacktestData
        if stock_data:
            prices: dict[str, pd.Series] = {}
            for sym, sdf in stock_data.items():
                sdf = sdf.copy()
                sdf["quote_date"] = pd.to_datetime(sdf["quote_date"])
                sdf = sdf.sort_values("quote_date").set_index("quote_date")
                prices[sym] = sdf["close"]
            self._data.stock_prices.update(prices)

        if benchmark_results:
            self._data = align_benchmarks(self._data, benchmark_results, benchmark_capitals or {})

        if benchmark_options and self._data.has_equity:
            start, end = self._data.equity_curve.index[[0, -1]]
            self._data.summary.update(compute_benchmarks(benchmark_options, start, end))

    @classmethod
    def from_evaluation(cls, evaluation, *, scope="full", scenario=None):
        """Create a research report from an EvaluationResult-compatible object.

        Scope is 'full' or 'common' (shared with stock price coverage). Cost
        scenarios use fixed historical fills, not a re-run execution model.
        """
        return make_evaluation_report(cls, evaluation, scope=scope, scenario=scenario)

    def plot_segments(self, *, kind="segment"):
        """Plot year, quarter or equal-time diagnostics of an evaluation report."""
        if not hasattr(self, "_evaluation_view"):
            raise ValueError("plot_segments requires BacktestReport.from_evaluation")
        return diagnostic_table(self._evaluation_view, kind)

    def export_trades(self, path):
        """Export all original completed trades, regardless of the display limit."""
        if hasattr(self, "_evaluation_view"):
            return self._evaluation_view.export_trades(path)
        self.data.trade_log.to_csv(path, index=False)
        return os.path.abspath(path)

    @property
    def data(self) -> BacktestData:
        """Access pre-extracted backtest data for custom panels."""
        return self._data

    @property
    def capital(self) -> float:
        """Initial capital."""
        return self._capital

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
        if hasattr(self, "_evaluation_view"):
            return evaluation_dashboard(self._evaluation_view)
        if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
            raise ValueError("columns must be a positive integer")
        if not self._panels:
            return go.Figure(layout={"title": self._title})
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

        row_heights = [
            max(float(fig.layout.height or 280) for _, fig, _ in panel_data[r * columns : (r + 1) * columns])
            for r in range(rows)
        ]
        plot_height = sum(row_heights) + 24 * (rows - 1)
        dash = make_subplots(
            rows=rows,
            cols=columns,
            specs=specs,
            subplot_titles=subplot_titles,
            row_heights=row_heights,
            vertical_spacing=24 / plot_height if rows > 1 else 0,
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
            autosize=True,
            height=plot_height + 80,
            margin={"t": 60, "b": 20},
        )
        return dash

    def save_html(self, path: str = "backtest_dashboard.html") -> str:
        """Render the dashboard and save to HTML.

        Args:
            path: Output HTML file path.

        Returns:
            The absolute path to the written HTML file.
        """
        if hasattr(self, "_evaluation_view"):
            return save_evaluation_html(self, path)
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
