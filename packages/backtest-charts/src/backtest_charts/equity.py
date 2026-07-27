"""Portfolio equity curve visualization."""

import altair as alt
import pandas as pd


def plot_equity_curve(result, initial_capital: float) -> alt.Chart:
    """Plot portfolio equity curve with a starting-capital reference line.

    Args:
        result: Object with ``equity_curve`` attribute (``pd.Series``, date-indexed).
        initial_capital: Starting capital for the reference line.

    Returns:
        Altair line chart of portfolio equity over time.
    """
    ec = result.equity_curve
    if ec is None or (isinstance(ec, pd.Series) and ec.empty):
        return _empty_chart("Portfolio Equity Curve", "No equity curve data")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(ec.index),
            "equity": ec.values,
        }
    )

    line = (
        alt.Chart(df)
        .mark_line(color="indigo", strokeWidth=2)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("equity:Q", title="Equity ($)", axis=alt.Axis(format="$,.0f")),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("equity:Q", title="Equity", format="$,.0f"),
            ],
        )
    )

    # Reference line at initial capital
    ref_df = pd.DataFrame({"initial_capital": [initial_capital]})
    ref = alt.Chart(ref_df).mark_rule(strokeDash=[6, 4], color="gray").encode(y=alt.Y("initial_capital:Q"))

    # Text label for the reference line
    ref_text = (
        alt.Chart(ref_df)
        .mark_text(align="left", dx=4, dy=-4, color="gray", fontSize=10)
        .encode(
            y=alt.Y("initial_capital:Q"),
            text=alt.value(f"Start ${initial_capital:,.0f}"),
        )
    )

    return (line + ref + ref_text).properties(title="Portfolio Equity Curve", width=600, height=300)


def _empty_chart(title: str, message: str) -> alt.Chart:
    """Return a chart that displays a placeholder message when data is missing."""
    return (
        alt.Chart()
        .mark_text(fontSize=14, color="gray")
        .encode(text=alt.value(message))
        .properties(title=title, width=600, height=300)
    )
