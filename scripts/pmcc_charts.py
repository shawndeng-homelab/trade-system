"""Plotly visualizations for PMCC backtest results.

Generates an interactive HTML dashboard from a ``PortfolioResult``:
equity curve, per-leg cumulative P&L, P&L distribution, and exit-type breakdown.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_portfolio(result, initial_capital: float, out_path: str = "pmcc_dashboard.html") -> str:
    """Render a multi-panel HTML dashboard and return its path.

    Args:
        result: ``optopsy.simulator.PortfolioResult``.
        initial_capital: Starting capital for the equity-curve baseline.
        out_path: Output HTML file path.

    Returns:
        The absolute path to the written HTML file.
    """
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Portfolio Equity Curve",
            "Cumulative P&L by Leg",
            "Per-Trade P&L Distribution",
            "Exit Type Breakdown",
        ),
        vertical_spacing=0.12,
        horizontal_spacing=0.10,
    )

    # ── 1. Equity curve ────────────────────────────────────────────────────
    ec = result.equity_curve
    if not ec.empty:
        idx = pd.to_datetime(ec.index)
        fig.add_trace(
            go.Scatter(
                x=idx,
                y=ec.values,
                mode="lines",
                name="Equity",
                line={"color": "indigo", "width": 2},
                hovertemplate="Date: %{x|%Y-%m-%d}<br>Equity: $%{y:,.0f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig.add_hline(
            y=initial_capital,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"Start ${initial_capital:,.0f}",
            row=1,
            col=1,
        )

    # ── 2. Cumulative P&L by leg ───────────────────────────────────────────
    log = result.trade_log
    if not log.empty and "leg" in log.columns:
        for leg_name in log["leg"].unique():
            leg_log = log[log["leg"] == leg_name].sort_values("exit_date")
            fig.add_trace(
                go.Scatter(
                    x=leg_log["exit_date"],
                    y=leg_log["realized_pnl"].cumsum(),
                    mode="lines+markers",
                    name=leg_name,
                    hovertemplate=f"{leg_name}<br>Date: %{{x}}<br>Cum P&L: $%{{y:,.0f}}<extra></extra>",
                ),
                row=1,
                col=2,
            )

    # ── 3. Per-trade P&L distribution ──────────────────────────────────────
    if not log.empty and "realized_pnl" in log.columns:
        colors = ["green" if p >= 0 else "crimson" for p in log["realized_pnl"]]
        fig.add_trace(
            go.Bar(
                x=list(range(1, len(log) + 1)),
                y=log["realized_pnl"],
                marker_color=colors,
                name="P&L",
                showlegend=False,
                hovertemplate="Trade %{x}<br>P&L: $%{y:,.0f}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    # ── 4. Exit type breakdown ─────────────────────────────────────────────
    if not log.empty and "exit_type" in log.columns and "leg" in log.columns:
        exit_counts = log.groupby(["leg", "exit_type"]).size().reset_index(name="count")
        for leg_name in exit_counts["leg"].unique():
            sub = exit_counts[exit_counts["leg"] == leg_name]
            fig.add_trace(
                go.Bar(
                    x=sub["exit_type"],
                    y=sub["count"],
                    name=f"{leg_name} exits",
                    hovertemplate=f"{leg_name} %{{x}}<br>Count: %{{y}}<extra></extra>",
                ),
                row=2,
                col=2,
            )

    fig.update_layout(
        title="PMCC Backtest Dashboard",
        height=800,
        width=1400,
        legend={"orientation": "h", "y": -0.05},
        template="plotly_white",
    )
    fig.update_xaxes(title_text="Date", row=1, col=1)
    fig.update_xaxes(title_text="Exit date", row=1, col=2)
    fig.update_xaxes(title_text="Trade #", row=2, col=1)
    fig.update_xaxes(title_text="Exit type", row=2, col=2)
    fig.update_yaxes(title_text="Equity ($)", row=1, col=1)
    fig.update_yaxes(title_text="Cumulative P&L ($)", row=1, col=2)
    fig.update_yaxes(title_text="P&L ($)", row=2, col=1)
    fig.update_yaxes(title_text="Count", row=2, col=2)

    import os

    out_abs = os.path.abspath(out_path)
    fig.write_html(out_abs)
    return out_abs
