"""Portfolio equity curve visualization with optional stock price overlay."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest_charts._util import _apply_chart_layout
from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


_TITLE = "Portfolio Equity Curve"

# Colors for stock price overlay lines
_STOCK_COLORS = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A"]

# Colors for benchmark equity overlay lines
_BENCHMARK_COLORS = ["#FF6B6B", "#4ECDC4", "#45B7D1"]


def plot_equity(data: BacktestData) -> go.Figure:
    """Plot portfolio equity curve with a starting-capital reference line.

    When ``data.stock_prices`` is populated, each symbol's close price is
    overlaid on a secondary y-axis as **percentage change from the start
    of the backtest**.  Both the equity curve and stock prices are shown
    as percentage change, so the two axes share the same scale and can
    be compared directly — e.g. "equity is up 5% while SPY is up 3%".

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly line chart of portfolio equity over time, with optional
        stock price overlay on a secondary axis (both as % change).
    """
    if not data.has_equity:
        return _empty_chart(_TITLE, "No equity curve data")

    ec = data.equity_curve
    capital = data.capital

    # Equity as percentage change from starting capital
    equity_pct = (ec / capital - 1) * 100

    has_stocks = bool(data.stock_prices)
    has_benchmarks = bool(data.benchmark_equity)
    needs_secondary = has_stocks
    fig = make_subplots(specs=[[{"secondary_y": True}]]) if needs_secondary else go.Figure()

    # Equity curve (primary y-axis, % change)
    fig.add_trace(
        go.Scatter(
            x=ec.index,
            y=equity_pct,
            mode="lines",
            line={"color": "indigo", "width": 2},
            name="Equity % Change",
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Equity: %{y:+.1f}%<extra></extra>",
        ),
        **({"secondary_y": False} if has_stocks else {}),
    )

    # Stock price overlay (secondary y-axis, % change from start)
    if has_stocks:
        ec_start = ec.index.min()
        ec_end = ec.index.max()
        for i, (sym, prices) in enumerate(data.stock_prices.items()):
            trimmed = prices[ec_start:ec_end]
            if trimmed.empty:
                continue
            # Normalize to % change from first price
            base_price = trimmed.iloc[0]
            if base_price <= 0:
                continue
            stock_pct = (trimmed / base_price - 1) * 100
            color = _STOCK_COLORS[i % len(_STOCK_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=stock_pct.index,
                    y=stock_pct,
                    mode="lines",
                    line={"color": color, "width": 1.5, "dash": "dot"},
                    name=f"{sym} % Change",
                    hovertemplate=f"{sym}: %{{y:+.1f}}%<extra></extra>",
                ),
                secondary_y=True,
            )

    # Benchmark equity overlay (primary y-axis, % change from start)
    if has_benchmarks:
        ec_start = ec.index.min()
        ec_end = ec.index.max()
        for i, (label, bm_curve) in enumerate(data.benchmark_equity.items()):
            trimmed = bm_curve[ec_start:ec_end]
            if trimmed.empty:
                continue
            # Normalize to % change from first value
            base_value = trimmed.iloc[0]
            if base_value <= 0:
                continue
            bm_pct = (trimmed / base_value - 1) * 100
            color = _BENCHMARK_COLORS[i % len(_BENCHMARK_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=bm_pct.index,
                    y=bm_pct,
                    mode="lines",
                    line={"color": color, "width": 1.5, "dash": "dash"},
                    name=f"{label} % Change",
                    hovertemplate=f"{label}: %{{y:+.1f}}%<extra></extra>",
                ),
                **({"secondary_y": False} if needs_secondary else {}),
            )

    # Reference line at 0% (starting capital)
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="gray",
        annotation_text="Start",
        annotation_position="top left",
        annotation_font_size=10,
        annotation_font_color="gray",
    )

    _apply_chart_layout(fig, _TITLE)
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Equity % Change",
        yaxis_ticksuffix="%",
        yaxis_zeroline=False,
    )

    if has_stocks:
        fig.update_yaxes(
            title_text="Stock % Change",
            ticksuffix="%",
            secondary_y=True,
            showgrid=False,
        )

    return fig


# Backward-compatible wrapper
def plot_equity_curve(result, initial_capital: float) -> go.Figure:
    """Plot portfolio equity curve (legacy API).

    .. deprecated:: 0.2.0
        Use :meth:`BacktestReport.plot_equity` instead.
    """
    return plot_equity(BacktestData.from_result(result, initial_capital))
