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
            ("annualized_return", "Annualized Return", "{:.1%}"),
            ("total_pnl", "Total P&L", "${:,.0f}"),
            ("profit_factor", "Profit Factor", "{:.2f}"),
            ("sharpe_ratio", "Sharpe Ratio", "{:.2f}"),
            ("sortino_ratio", "Sortino Ratio", "{:.2f}"),
            ("calmar_ratio", "Calmar Ratio", "{:.2f}"),
            ("mar_ratio", "MAR Ratio", "{:.2f}"),
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
    When benchmark data is present in the summary dict, each benchmark
    symbol gets its own Value column so the strategy is compared side
    by side against buy-and-hold ATM call returns.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly table figure with strategy metrics.
    """
    if not data.has_trades:
        return _empty_chart(_TITLE, "No trade data")

    summary = data.summary

    # Detect which benchmarks are available
    # Priority: benchmark_summaries (from benchmark_results) > benchmark_* keys (from compute_benchmarks)
    benchmark_labels = list(data.benchmark_summaries.keys())
    benchmark_syms = [k.replace("benchmark_", "") for k in summary if k.startswith("benchmark_")]
    # Merge: benchmark_summaries labels are the primary columns, add any legacy benchmark_* symbols not already covered
    all_benchmark_keys = list(benchmark_labels)
    for sym in benchmark_syms:
        if sym not in all_benchmark_keys:
            all_benchmark_keys.append(sym)

    # Build column headers
    header_values = ["<b>Metric</b>", "<b>Strategy</b>"]
    for key in all_benchmark_keys:
        # Use symbol name for legacy benchmark_* keys, label as-is for benchmark_summaries keys
        header_values.append(f"<b>{key} ATM Call</b>")

    # Build rows
    metric_names: list[str] = []
    strategy_values: list[str] = []
    benchmark_values: dict[str, list[str]] = {key: [] for key in all_benchmark_keys}
    fill_colors: dict[str, list[str]] = {"name": [], "strategy": []}
    for key in all_benchmark_keys:
        fill_colors[key] = []

    group_bg = "#f0f0f0"
    row_bg = "white"

    for group_name, metrics in _METRIC_GROUPS:
        # Group header row
        metric_names.append(f"<b>{group_name}</b>")
        strategy_values.append("")
        for key in all_benchmark_keys:
            benchmark_values[key].append("")
        fill_colors["name"].append(group_bg)
        fill_colors["strategy"].append(group_bg)
        for key in all_benchmark_keys:
            fill_colors[key].append(group_bg)

        for key, label, fmt in metrics:
            metric_names.append(f"  {label}")
            strategy_values.append(_format_value(summary.get(key), fmt))
            for bm_key in all_benchmark_keys:
                # Use benchmark_summaries if available, else fall back to legacy benchmark_* keys
                bm_summary = data.benchmark_summaries.get(bm_key)
                if bm_summary:
                    benchmark_values[bm_key].append(_format_value(bm_summary.get(key), fmt))
                else:
                    benchmark_values[bm_key].append("—")
            fill_colors["name"].append(row_bg)
            fill_colors["strategy"].append(row_bg)
            for bm_key in all_benchmark_keys:
                fill_colors[bm_key].append(row_bg)

    # ── Benchmark rows: ATM call return ──────────────────────────────────
    metric_names.append("<b>Benchmark (Rolling ATM Call)</b>")
    strategy_values.append("")
    for bm_key in all_benchmark_keys:
        benchmark_values[bm_key].append("")
    fill_colors["name"].append(group_bg)
    fill_colors["strategy"].append(group_bg)
    for bm_key in all_benchmark_keys:
        fill_colors[bm_key].append(group_bg)

    for bm_key in all_benchmark_keys:
        metric_names.append(f"  {bm_key} ATM Call Return")
        strategy_values.append("—")
        for other_key in all_benchmark_keys:
            if other_key == bm_key:
                # Prefer benchmark_summaries total_return, fall back to legacy benchmark_* key
                bm_summary = data.benchmark_summaries.get(bm_key)
                if bm_summary and "total_return" in bm_summary:
                    benchmark_values[other_key].append(_format_value(bm_summary["total_return"], "{:.1%}"))
                else:
                    benchmark_values[other_key].append(_format_value(summary.get(f"benchmark_{bm_key}"), "{:.1%}"))
            else:
                benchmark_values[other_key].append("—")
        fill_colors["name"].append(row_bg)
        fill_colors["strategy"].append(row_bg)
        for s in all_benchmark_keys:
            fill_colors[s].append(row_bg)

    # Assemble cells
    cells_values = [metric_names, strategy_values] + [benchmark_values[key] for key in all_benchmark_keys]
    cells_fill = [fill_colors["name"], fill_colors["strategy"]] + [fill_colors[key] for key in all_benchmark_keys]

    col_widths = [220, 120] + [100] * len(all_benchmark_keys)

    fig = go.Figure(
        go.Table(
            header={
                "values": header_values,
                "fill_color": "indigo",
                "font": {"color": "white", "size": 12},
                "align": "left",
                "height": 30,
            },
            cells={
                "values": cells_values,
                "fill_color": cells_fill,
                "align": ["left", "right"] + ["right"] * len(all_benchmark_keys),
                "height": 24,
                "font": {"size": 11},
            },
            columnwidth=col_widths,
        )
    )
    # Extra height for benchmark section
    table_height = 580 + len(all_benchmark_keys) * 28
    _apply_chart_layout(fig, _TITLE, height=table_height)
    fig.update_layout(margin={"l": 10, "r": 10, "t": 50, "b": 10})
    return fig
