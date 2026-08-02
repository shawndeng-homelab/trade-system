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
from backtest_charts.data import BacktestData
from backtest_charts.data import compute_benchmarks
from backtest_charts.equity import plot_equity
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

    def __init__(
        self,
        result,
        capital: float = DEFAULT_CAPITAL,
        *,
        title: str = "Backtest Dashboard",
        benchmark_options: dict[str, "pd.DataFrame"] | None = None,
        stock_data: dict[str, "pd.DataFrame"] | None = None,
        benchmark_results: dict[str, object] | None = None,
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
                close price on a secondary y-axis (log scale).  Each DataFrame
                must have columns: ``quote_date``, ``close``.
            benchmark_results: Optional mapping of label → backtest result
                object (duck-typed with ``equity_curve`` attribute).  When
                provided, each result's equity curve is overlaid on the
                equity chart as a dashed line (percentage change from start),
                enabling visual comparison against benchmark strategies.
        """
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

        # Inject benchmark equity curves and summaries into BacktestData
        if benchmark_results:
            bm_equity: dict[str, pd.Series] = {}
            bm_summaries: dict[str, dict] = {}
            for label, bm_result in benchmark_results.items():
                ec = getattr(bm_result, "equity_curve", None)
                if ec is not None and not ec.empty:
                    ec = ec.copy()
                    if not isinstance(ec.index, pd.DatetimeIndex):
                        ec.index = pd.to_datetime(ec.index)
                    bm_equity[label] = ec
                bm_summary = getattr(bm_result, "summary", None)
                if bm_summary and isinstance(bm_summary, dict):
                    # Compute annualized return for benchmark
                    bm_total_return = bm_summary.get("total_return")
                    if bm_total_return is not None and not ec.empty:
                        bm_start = pd.Timestamp(ec.index.min())
                        bm_end = pd.Timestamp(ec.index.max())
                        bm_years = (bm_end - bm_start).days / 365.25
                        if bm_years > 0:
                            bm_summary["annualized_return"] = (1 + bm_total_return) ** (1 / bm_years) - 1
                    bm_summaries[label] = bm_summary
            self._data.benchmark_equity.update(bm_equity)
            self._data.benchmark_summaries.update(bm_summaries)

        # Compute benchmarks and inject into summary dict
        if benchmark_options and self._data.has_trades:
            tl = self._data.trade_log
            start = pd.Timestamp(tl["entry_date"].min())
            end = pd.Timestamp(tl["exit_date"].max())
            benchmarks = compute_benchmarks(benchmark_options, start, end)
            # Mutate the summary dict (BacktestData is frozen but summary is a dict)
            self._data.summary.update(benchmarks)

        # Compute annualized return and MAR ratio
        if self._data.has_trades:
            tl = self._data.trade_log
            start = pd.Timestamp(tl["entry_date"].min())
            end = pd.Timestamp(tl["exit_date"].max())
            years = (end - start).days / 365.25
            summary = self._data.summary
            total_return = summary.get("total_return")
            max_dd = summary.get("max_drawdown")
            if years > 0 and total_return is not None:
                summary["annualized_return"] = (1 + total_return) ** (1 / years) - 1
            if total_return is not None and max_dd is not None and max_dd != 0:
                summary["mar_ratio"] = total_return / abs(max_dd)

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
            autosize=True,
            height=280 * rows + 80,
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
