"""Trade log table visualization.

Shows every trade in the backtest with key details: entry/exit dates,
strike, P&L, exit type, days held, etc.
"""

import pandas as pd
import plotly.graph_objects as go

from backtest_charts._util import _apply_chart_layout
from backtest_charts._util import _empty_chart
from backtest_charts.data import BacktestData


_TITLE = "Trade Log"

# Columns to display: (source_column, display_header)
_DISPLAY_COLUMNS: list[tuple[str, str]] = [
    ("trade_id", "Trade #"),
    ("leg", "Leg"),
    ("underlying_symbol", "Symbol"),
    ("entry_date", "Entry Date"),
    ("exit_date", "Exit Date"),
    ("expiration", "Expiration"),
    ("description", "Description"),
    ("entry_cost", "Entry Cost"),
    ("exit_proceeds", "Exit Proceeds"),
    ("realized_pnl", "P&L"),
    ("pct_change", "P&L %"),
    ("exit_type", "Exit Type"),
    ("days_held", "Days Held"),
]


def _format_date(val: object) -> str:
    """Format a date value for display."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    try:
        ts = pd.Timestamp(val)
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(val)


def _format_money(val: object) -> str:
    """Format a monetary value for display."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    try:
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return str(val)


def _format_pct(val: object) -> str:
    """Format a percentage value for display."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    try:
        return f"{val:.1%}"
    except (ValueError, TypeError):
        return str(val)


def plot_trades(data: BacktestData) -> go.Figure:
    """Plot trade log as a detailed table.

    Each row shows one trade with entry/exit dates, P&L, exit type,
    and other key fields.  Positive P&L rows are highlighted green,
    negative P&L rows are highlighted red.

    Args:
        data: Pre-extracted backtest data.

    Returns:
        Plotly table figure with trade details.
    """
    if not data.has_trades:
        return _empty_chart(_TITLE, "No trade data")

    log = data.trade_log

    # Build columns, only including those present in the trade log
    headers: list[str] = []
    columns: list[list[str]] = []

    for src_col, display_name in _DISPLAY_COLUMNS:
        if src_col not in log.columns:
            continue
        headers.append(display_name)
        raw = log[src_col]
        # Format values based on column type
        if src_col in ("entry_date", "exit_date", "expiration"):
            columns.append([_format_date(v) for v in raw])
        elif src_col in ("entry_cost", "exit_proceeds", "realized_pnl"):
            columns.append([_format_money(v) for v in raw])
        elif src_col == "pct_change":
            columns.append([_format_pct(v) for v in raw])
        elif src_col == "trade_id" or src_col == "days_held":
            columns.append([str(int(v)) if not pd.isna(v) else "—" for v in raw])
        else:
            columns.append([str(v) if not pd.isna(v) else "—" for v in raw])

    # Color rows by P&L
    if "realized_pnl" in log.columns:
        pnl = log["realized_pnl"]
        row_colors = ["rgba(0,180,0,0.08)" if v >= 0 else "rgba(220,20,20,0.08)" for v in pnl]
    else:
        row_colors = ["white"] * len(log)

    # Build per-cell fill colors (same color across all columns in a row)
    fill_color = [row_colors] * len(headers)

    fig = go.Figure(
        go.Table(
            header={
                "values": [f"<b>{h}</b>" for h in headers],
                "fill_color": "indigo",
                "font": {"color": "white", "size": 10},
                "align": "center",
                "height": 28,
            },
            cells={
                "values": columns,
                "fill_color": fill_color,
                "align": ["center"] * len(headers),
                "height": 22,
                "font": {"size": 9},
            },
        )
    )
    # Trade log table is taller than other panels
    n_rows = len(log)
    table_height = min(max(300, n_rows * 26 + 60), 800)
    _apply_chart_layout(fig, _TITLE, height=table_height)
    fig.update_layout(margin={"l": 10, "r": 10, "t": 50, "b": 10})
    return fig
