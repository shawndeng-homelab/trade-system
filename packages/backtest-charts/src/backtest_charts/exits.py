"""Exit-type analysis visualization."""

import altair as alt

from backtest_charts.equity import _empty_chart


def plot_exit_breakdown(result) -> alt.Chart:
    """Plot exit-type count grouped by leg.

    Args:
        result: Object with ``trade_log`` attribute (``pd.DataFrame`` with
            ``exit_type`` and ``leg`` columns).

    Returns:
        Altair grouped bar chart of exit counts by type and leg.
    """
    log = result.trade_log
    if log is None or log.empty or "exit_type" not in log.columns or "leg" not in log.columns:
        return _empty_chart("Exit Type Breakdown", "No exit type data")

    counts = log.groupby(["leg", "exit_type"]).size().reset_index(name="count")

    return (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("exit_type:N", title="Exit type"),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("leg:N", title="Leg"),
            xOffset="leg:N",
            tooltip=[
                alt.Tooltip("leg:N", title="Leg"),
                alt.Tooltip("exit_type:N", title="Exit type"),
                alt.Tooltip("count:Q", title="Count"),
            ],
        )
        .properties(title="Exit Type Breakdown", width=600, height=300)
    )
