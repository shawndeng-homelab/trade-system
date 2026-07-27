"""P&L visualizations: cumulative P&L by leg and per-trade distribution."""

import altair as alt
import pandas as pd

from backtest_charts.equity import _empty_chart


def plot_cumulative_pnl(result) -> alt.Chart:
    """Plot cumulative realized P&L by leg.

    Args:
        result: Object with ``trade_log`` attribute (``pd.DataFrame`` with ``leg``,
            ``exit_date``, and ``realized_pnl`` columns).

    Returns:
        Altair multi-line chart of cumulative P&L per leg over time.
    """
    log = result.trade_log
    if log is None or log.empty or "leg" not in log.columns:
        return _empty_chart("Cumulative P&L by Leg", "No trade log data")

    rows = []
    for leg_name in log["leg"].unique():
        leg_log = log[log["leg"] == leg_name].sort_values("exit_date").copy()
        leg_log["cumulative_pnl"] = leg_log["realized_pnl"].cumsum()
        leg_log["leg"] = leg_name
        rows.append(leg_log[["exit_date", "cumulative_pnl", "leg"]])

    df = pd.concat(rows, ignore_index=True)

    return (
        alt.Chart(df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("exit_date:T", title="Exit date"),
            y=alt.Y("cumulative_pnl:Q", title="Cumulative P&L ($)", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("leg:N", title="Leg"),
            tooltip=[
                alt.Tooltip("leg:N", title="Leg"),
                alt.Tooltip("exit_date:T", title="Date"),
                alt.Tooltip("cumulative_pnl:Q", title="Cum P&L", format="$,.0f"),
            ],
        )
        .properties(title="Cumulative P&L by Leg", width=580, height=280)
        .add_params(alt.selection_point(name="cum_pnl_zoom", encodings=["x", "y"], bind="scales"))
    )


def plot_pnl_distribution(result) -> alt.Chart:
    """Plot per-trade realized P&L as a bar chart.

    Positive P&L bars are green, negative are crimson.

    Args:
        result: Object with ``trade_log`` attribute (``pd.DataFrame`` with
            ``realized_pnl`` column; ``trade_id``, ``exit_type``, ``leg`` optional).

    Returns:
        Altair bar chart of per-trade P&L.
    """
    log = result.trade_log
    if log is None or log.empty or "realized_pnl" not in log.columns:
        return _empty_chart("Per-Trade P&L Distribution", "No trade log data")

    df = log.copy()
    if "trade_id" not in df.columns:
        df["trade_id"] = range(1, len(df) + 1)
    df = df[["trade_id", "realized_pnl"] + [c for c in ("exit_type", "leg") if c in df.columns]]
    df["profitable"] = (df["realized_pnl"] >= 0).astype(str)

    tooltip = [
        alt.Tooltip("trade_id:Q", title="Trade #"),
        alt.Tooltip("realized_pnl:Q", title="P&L", format="$,.0f"),
    ]
    if "exit_type" in df.columns:
        tooltip.append(alt.Tooltip("exit_type:N", title="Exit type"))
    if "leg" in df.columns:
        tooltip.append(alt.Tooltip("leg:N", title="Leg"))

    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("trade_id:O", title="Trade #", axis=alt.Axis(labelOverlap=True)),
            y=alt.Y("realized_pnl:Q", title="P&L ($)", axis=alt.Axis(format="$,.0f")),
            color=alt.Color(
                "profitable:N",
                scale=alt.Scale(domain=["True", "False"], range=["green", "crimson"]),
                legend=None,
            ),
            tooltip=tooltip,
        )
        .properties(title="Per-Trade P&L Distribution", width=alt.Step(14), height=280)
    )
