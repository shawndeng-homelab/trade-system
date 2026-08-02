"""Strategy summary table visualization."""

import plotly.graph_objects as go

from backtest_charts._util import _apply_chart_layout
from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


_TITLE = "Strategy Summary"

# Metric definitions: (dict_key, display_label, format_string)
_METRIC_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Performance",
        [
            ("total_return", "Total Return", "{:.1%}"),
            ("total_pnl", "Total P&L", "${:,.0f}"),
            ("profit_factor", "Profit Factor", "{:.2f}"),
            ("sharpe_ratio", "Sharpe Ratio", "{:.2f}"),
            ("sortino_ratio", "Sortino Ratio", "{:.2f}"),
            ("calmar_ratio", "Calmar Ratio", "{:.2f}"),
            ("omega_ratio", "Omega Ratio", "{:.2f}"),
            ("tail_ratio", "Tail Ratio", "{:.2f}"),
        ],
    ),
    (
        "Risk",
        [
            ("max_drawdown", "Max Drawdown", "{:.1%}"),
            ("var_95", "VaR (95%)", "{:.2%}"),
            ("cvar_95", "CVaR (95%)", "{:.2%}"),
            ("max_loss", "Max Loss", "${:,.0f}"),
        ],
    ),
    (
        "Trading",
        [
            ("total_trades", "Total Trades", "{:d}"),
            ("winning_trades", "Winning Trades", "{:d}"),
            ("losing_trades", "Losing Trades", "{:d}"),
            ("win_rate", "Win Rate", "{:.1%}"),
            ("avg_pnl", "Avg P&L", "${:,.0f}"),
            ("avg_win", "Avg Win", "${:,.0f}"),
            ("avg_loss", "Avg Loss", "${:,.0f}"),
            ("max_win", "Max Win", "${:,.0f}"),
            ("avg_days_in_trade", "Avg Days Held", "{:.1f}"),
        ],
    ),
]


def _format_value(value: object, fmt: str) -> str:
    """Format a metric value using its format string.

    For integer formats (``{:d}``), the value is cast to ``int`` first
    to handle float-backed integer fields from optopsy.

    Args:
        value: The metric value (may be ``None``).
        fmt: A Python format string (e.g. ``"{:.1%}"``, ``"{:d}"``).

    Returns:
        Formatted string, or ``"—"`` if value is ``None``.
    """
    if value is None:
        return "—"
    try:
        if fmt.endswith("d}"):
            return fmt.format(int(value))
        return fmt.format(value)
    except (ValueError, TypeError):
        return str(value)


def plot_summary(data: BacktestData) -> go.Figure:
    """Plot strategy summary metrics as a table.

    Metrics are grouped into Performance, Risk, and Trading categories.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly table figure with strategy metrics.
    """
    if not data.has_trades:
        return _empty_chart(_TITLE, "No trade data")

    summary = data.summary
    metric_names: list[str] = []
    metric_values: list[str] = []
    fill_colors: list[list[str]] = [[], []]

    group_bg = "#f0f0f0"
    row_bg = "white"

    for group_name, metrics in _METRIC_GROUPS:
        # Group header row
        metric_names.append(f"<b>{group_name}</b>")
        metric_values.append("")
        fill_colors[0].append(group_bg)
        fill_colors[1].append(group_bg)
        for key, label, fmt in metrics:
            metric_names.append(f"  {label}")
            metric_values.append(_format_value(summary.get(key), fmt))
            fill_colors[0].append(row_bg)
            fill_colors[1].append(row_bg)

    fig = go.Figure(
        go.Table(
            header={
                "values": ["<b>Metric</b>", "<b>Value</b>"],
                "fill_color": "indigo",
                "font": {"color": "white", "size": 12},
                "align": "left",
                "height": 30,
            },
            cells={
                "values": [metric_names, metric_values],
                "fill_color": fill_colors,
                "align": ["left", "right"],
                "height": 24,
                "font": {"size": 11},
            },
            columnwidth=[300, 200],
        )
    )
    _apply_chart_layout(fig, _TITLE, height=580)
    fig.update_layout(margin={"l": 10, "r": 10, "t": 50, "b": 10})
    return fig
