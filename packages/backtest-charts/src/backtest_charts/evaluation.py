"""Research dashboard consuming portable evaluation fields, without optopsy imports."""

import dataclasses
import html
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest_charts.metrics import curve_metrics


COLORS = {
    "PMCC": "#2455A4",
    "LEAPS-only": "#198078",
    "Cash (0%)": "#8A919C",
    "leaps": "#198078",
    "short_call": "#BF7126",
}


class EvaluationView:
    """An explicit full-period or common-period view of one cost scenario."""

    def __init__(self, evaluation, scope="full", scenario=None):
        """Select one cost scenario and an explicit date interval."""
        if scope not in {"full", "common"}:
            raise ValueError("scope must be 'full' or 'common'")
        self.evaluation = evaluation
        self.scope = scope
        self.scenario = scenario or evaluation.metadata["evaluation_config"]["primary_scenario"]
        if self.scenario not in evaluation.curves.scenario.unique():
            raise ValueError(f"Unknown cost scenario: {self.scenario}")
        self.start = pd.Timestamp(evaluation.metadata["start"])
        self.end = pd.Timestamp(evaluation.metadata["end"])
        if scope == "common":
            self.start = max(self.start, evaluation.stock_prices.index.min())
            self.end = min(self.end, evaluation.stock_prices.index.max())
            if self.start > self.end:
                raise ValueError("No common evaluation and price-reference interval")
        self.capital = evaluation.metadata["capital"]
        self.ledger = evaluation.ledger[evaluation.ledger.scenario == self.scenario].copy()
        self.trades = evaluation.trades[evaluation.trades.exit_date.between(self.start, self.end)].copy()
        pmcc_events = self.ledger[self.ledger.strategy == "PMCC"]
        costs = pmcc_events.groupby("trade_key")[["commission", "slippage"]].sum()
        self.trades["commission"] = self.trades.trade_key.map(costs.commission).fillna(0)
        self.trades["slippage"] = self.trades.trade_key.map(costs.slippage).fillna(0)
        self.trades["net_trade_pnl"] = self.trades.realized_pnl - self.trades.commission - self.trades.slippage
        self.trades["scenario"] = self.scenario

    def export_trades(self, path):
        """Export all completed trades with full-round-trip costs in this scenario."""
        full = EvaluationView(self.evaluation, scope="full", scenario=self.scenario)
        full.trades.to_csv(path, index=False)
        return str(Path(path).resolve())

    def curve(self, strategy="PMCC", scenario=None):
        """Get the displayed equity and its pre-window cash baseline."""
        scenario = scenario or self.scenario
        table = self.evaluation.curves
        curve = table[(table.scenario == scenario) & (table.strategy == strategy)].set_index("date").equity
        events = self.evaluation.ledger
        before = events[(events.scenario == scenario) & (events.strategy == strategy) & (events.date < self.start)]
        base = self.capital + before.net_pnl.sum()
        return curve.loc[self.start : self.end], float(base)

    def summary(self, strategy="PMCC", scenario=None):
        """Recalculate window metrics, not full-run metrics on a clipped curve."""
        curve, base = self.curve(strategy, scenario)
        if base <= 0:
            return {"total_return": None, "max_drawdown": None, "total_pnl": float(curve.iloc[-1] - base)}
        return curve_metrics(curve, base)

    def events(self, strategy="PMCC"):
        """Cash events in the selected interval."""
        return self.ledger[(self.ledger.strategy == strategy) & self.ledger.date.between(self.start, self.end)]


def make_evaluation_report(cls, evaluation, *, scope="full", scenario=None):
    """Build a normal report with explicitly prepared research data."""
    view = EvaluationView(evaluation, scope, scenario)
    curve, base = view.curve()
    if base <= 0:
        raise ValueError("The selected comparison interval starts with non-positive equity")
    report = cls(SimpleNamespace(equity_curve=curve, summary=view.summary()), capital=base)
    bm_curve, bm_base = view.curve("LEAPS-only")
    benchmarks = {"Cash (0%)": pd.Series(base, index=curve.index)}
    benchmark_capitals = {"Cash (0%)": base}
    if bm_base > 0:
        benchmarks["LEAPS-only"] = bm_curve
        benchmark_capitals["LEAPS-only"] = bm_base
    trades = view.trades.copy()
    trades["realized_pnl"] = trades.net_trade_pnl
    report._data = dataclasses.replace(
        report.data,
        trade_log=trades,
        benchmark_equity=benchmarks,
        benchmark_capitals=benchmark_capitals,
        benchmark_summaries={"LEAPS-only": view.summary("LEAPS-only")},
    )
    report._capital = evaluation.metadata["capital"]
    report._evaluation_view = view
    return report


def _line(fig, x, y, name, row, col=1, *, color=None, dash=None, legend=True, group=None, shape="hv"):
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            name=name,
            mode="lines",
            legendgroup=group or name,
            showlegend=legend,
            line={"color": color or COLORS.get(name, "#6D7380"), "width": 2, "dash": dash, "shape": shape},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra>%{fullData.name}</extra>",
        ),
        row=row,
        col=col,
    )


def evaluation_dashboard(view):
    """Render fixed-fill diagnostics with separate price and realized-equity panels."""
    specs = [
        [{"type": "indicator"}] * 4,
        [{"colspan": 4}, None, None, None],
        [{"colspan": 4}, None, None, None],
        [{"colspan": 2}, None, {"colspan": 2}, None],
        [{"colspan": 2}, None, {"colspan": 2}, None],
        [{"colspan": 2}, None, {"colspan": 2}, None],
        [{"type": "table", "colspan": 4}, None, None, None],
    ]
    titles = [
        "",
        "",
        "",
        "",
        "Realized equity · net of costs",
        "Realized drawdown",
        "Cost scenarios · fixed fills",
        "Quarterly net P&L · event dates",
        "Completed-trade net P&L distribution",
        "Underlying price reference · different valuation basis",
        "Net realized P&L by leg · event dates",
        "Exit reasons · net round-trip P&L",
        "Latest 50 completed trades · full round-trip costs",
    ]
    fig = make_subplots(
        rows=7,
        cols=4,
        specs=specs,
        subplot_titles=titles,
        row_heights=[90, 330, 150, 260, 260, 260, 390],
        vertical_spacing=0.035,
        horizontal_spacing=0.07,
    )
    summary = view.summary()
    events = view.events()
    cost = float(events.commission.sum() + events.slippage.sum())
    indicators = [
        ("Net realized return", summary.get("total_return"), "%", 100),
        ("Realized max drawdown", summary.get("max_drawdown"), "%", 100),
        ("Period costs", cost, "", 1),
        ("Completed trades", len(view.trades), "", 1),
    ]
    for i, (label, value, suffix, scale) in enumerate(indicators, 1):
        number = {"suffix": suffix, "valueformat": ".2f" if i < 3 else ",.0f", "font": {"size": 30}}
        if i == 3:
            number["prefix"] = "$"
        fig.add_trace(
            go.Indicator(
                mode="number",
                value=value * scale if value is not None else float("nan"),
                number=number,
                title={"text": label, "font": {"size": 13}},
            ),
            row=1,
            col=i,
        )
    for strategy in ("PMCC", "LEAPS-only"):
        curve, base = view.curve(strategy)
        if base <= 0:
            continue
        _line(
            fig, curve.index, (curve / base - 1) * 100, strategy, 2, dash="dash" if strategy == "LEAPS-only" else None
        )
        dd = (curve / curve.cummax().clip(lower=base) - 1) * 100
        _line(fig, dd.index, dd, strategy, 3, legend=False)
    curve, _ = view.curve()
    _line(fig, curve.index, [0] * len(curve), "Cash (0%)", 2, dash="dot")
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    fig.update_yaxes(ticksuffix="%", row=3, col=1)
    fig.update_xaxes(matches="x", row=3, col=1)
    for strategy in ("PMCC", "LEAPS-only"):
        names = view.evaluation.curves.scenario.unique().tolist()
        values = [view.summary(strategy, name)["total_pnl"] for name in names]
        fig.add_trace(
            go.Bar(
                x=names,
                y=values,
                name=strategy,
                marker_color=COLORS[strategy],
                legendgroup=strategy,
                showlegend=False,
                hovertemplate="%{x}<br>Net P&L: $%{y:,.2f}<extra>%{fullData.name}</extra>",
            ),
            row=4,
            col=1,
        )
    if not events.empty:
        quarters = events.assign(quarter=events.date.dt.to_period("Q")).groupby("quarter").net_pnl.sum()
    else:
        quarters = pd.Series(dtype=float)
    periods = pd.period_range(view.start, view.end, freq="Q")
    quarters = quarters.reindex(periods, fill_value=0)
    years = sorted({p.year for p in periods})
    values = [[float(quarters.get(pd.Period(f"{year}Q{q}"), float("nan"))) for q in range(1, 5)] for year in years]
    fig.add_trace(
        go.Heatmap(
            z=values,
            x=["Q1", "Q2", "Q3", "Q4"],
            y=[str(y) for y in years],
            colorscale="RdBu",
            zmid=0,
            showscale=False,
            hovertemplate="%{y} %{x}<br>Net P&L: $%{z:,.2f}<extra></extra>",
        ),
        row=4,
        col=3,
    )
    fig.add_trace(
        go.Histogram(
            x=view.trades.net_trade_pnl,
            nbinsx=min(30, max(5, len(view.trades))),
            name="Trades",
            marker_color=COLORS["PMCC"],
            showlegend=False,
            hovertemplate="P&L bin: %{x}<br>Trades: %{y}<extra></extra>",
        ),
        row=5,
        col=1,
    )
    fig.add_vline(exclude_empty_subplots=False, x=0, line_dash="dot", line_color="#8A919C", row=5, col=1)
    if not view.trades.empty:
        fig.add_vline(
            exclude_empty_subplots=False,
            x=float(view.trades.net_trade_pnl.median()),
            line_dash="dash",
            line_color="#BF7126",
            annotation_text="Median",
            row=5,
            col=1,
        )
    prices = view.evaluation.stock_prices.loc[view.start : view.end]
    if not prices.empty:
        _line(
            fig,
            prices.index,
            (prices / prices.iloc[0] - 1) * 100,
            f"{view.evaluation.metadata['symbol']} price",
            5,
            3,
            color="#6D7380",
            legend=False,
            shape="linear",
        )
    fig.update_yaxes(ticksuffix="%", row=5, col=3)
    for leg in ("leaps", "short_call"):
        net = events[events.leg == leg].groupby("date").net_pnl.sum().reindex(curve.index, fill_value=0).cumsum()
        _line(fig, net.index, net, leg, 6)
    if "exit_type" in view.trades:
        exits = view.trades.groupby("exit_type").net_trade_pnl.agg(["sum", "mean", "size"])
        fig.add_trace(
            go.Bar(
                x=exits.index,
                y=exits["sum"],
                showlegend=False,
                marker_color=["#198078" if v >= 0 else "#B84949" for v in exits["sum"]],
                customdata=exits[["mean", "size"]].values,
                hovertemplate=(
                    "%{x}<br>Net: $%{y:,.2f}<br>Average: $%{customdata[0]:,.2f}"
                    "<br>Count: %{customdata[1]}<extra></extra>"
                ),
            ),
            row=6,
            col=3,
        )
    table = view.trades.sort_values("exit_date", ascending=False).head(50)
    columns = [
        c
        for c in ("trade_key", "leg", "entry_date", "exit_date", "realized_pnl", "net_trade_pnl", "exit_type")
        if c in table
    ]
    headers = {
        "trade_key": "ID",
        "leg": "Leg",
        "entry_date": "Entry",
        "exit_date": "Exit",
        "realized_pnl": "Gross P&L",
        "net_trade_pnl": "Net round trip",
        "exit_type": "Exit reason",
    }
    cell_values = []
    for column in columns:
        if column.endswith("date"):
            cell_values.append(table[column].dt.strftime("%Y-%m-%d").tolist())
        elif column.endswith("pnl"):
            cell_values.append([f"${v:,.2f}" for v in table[column]])
        else:
            cell_values.append(table[column].tolist())
    fig.add_trace(
        go.Table(
            header={"values": [headers[c] for c in columns], "fill_color": "#E9EEF5", "height": 30},
            cells={"values": cell_values, "height": 24, "font": {"size": 12}, "fill_color": "white"},
        ),
        row=7,
        col=1,
    )
    title = (
        f"PMCC evaluation · {view.scope} · {html.escape(view.scenario)}"
        f"<br><sup>{view.start:%Y-%m-%d} — {view.end:%Y-%m-%d} · completed trades only · no mark-to-market</sup>"
    )
    contribution = float(view.events().net_pnl.sum() - view.events("LEAPS-only").net_pnl.sum())
    title += f"<br><sup>Short-call net contribution: ${contribution:,.2f} · fixed-fill comparison</sup>"
    flags = view.evaluation.summaries
    insolvent = flags[(flags.scenario == view.scenario) & flags.capital_insufficient].strategy.tolist()
    if insolvent:
        title += f"<br><sup>Capital insufficient ({', '.join(insolvent)}): not an executable simulation.</sup>"
    fig.update_layout(
        title={"text": title, "x": 0.03},
        template="plotly_white",
        height=2300,
        font={"family": "Arial, sans-serif", "size": 12, "color": "#273345"},
        hovermode="x unified",
        barmode="group",
        margin={"l": 65, "r": 40, "t": 150, "b": 40},
        legend={"orientation": "h", "y": 1.04, "x": 0},
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#EDF0F4", zerolinecolor="#C6CDD8")
    return fig


def diagnostic_table(view, kind="segment"):
    """Render scope-specific descriptive diagnostics, with undefined values blank."""
    if kind not in {"segment", "year", "quarter"}:
        raise ValueError("kind must be segment, year or quarter")
    data = view.evaluation.diagnostics(view.scenario, start=view.start, end=view.end)
    data = data[data.kind == kind]
    columns = [
        "label",
        "strategy",
        "start",
        "end",
        "net_pnl",
        "incremental_vs_leaps",
        "total_return",
        "max_drawdown",
        "total_trades",
        "max_loss",
        "top5_profit_share",
    ]
    names = [
        "Period",
        "Strategy",
        "Start",
        "End",
        "Net P&L",
        "Short-call P&L",
        "Realized return",
        "Realized drawdown",
        "Trades",
        "Worst trade",
        "Top 5 / gross profits",
    ]
    values = []
    for column in columns:
        if column in ("start", "end"):
            values.append(data[column].dt.strftime("%Y-%m-%d").tolist())
        elif column in ("total_return", "max_drawdown", "top5_profit_share"):
            values.append(["—" if pd.isna(v) else f"{v:.2%}" for v in data[column]])
        elif column in ("net_pnl", "max_loss", "incremental_vs_leaps"):
            values.append(["—" if pd.isna(v) else f"${v:,.2f}" for v in data[column]])
        else:
            values.append(data[column].tolist())
    fig = go.Figure(
        go.Table(
            header={"values": names, "fill_color": "#E9EEF5", "height": 32},
            cells={"values": values, "height": 28, "fill_color": "white", "font": {"size": 12}},
        )
    )
    fig.update_layout(
        title=f"{kind.title()} diagnostics · {view.start:%Y-%m-%d} — {view.end:%Y-%m-%d} · descriptive only",
        height=max(240, 100 + 28 * len(data)),
        margin={"l": 10, "r": 10, "t": 65, "b": 15},
    )
    return fig


def save_evaluation_html(report, path):
    """Self-contained HTML with explicit assumptions and coverage before the figure."""
    view = report._evaluation_view
    metadata = view.evaluation.metadata
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in metadata["limitations"])
    config = metadata["evaluation_config"]
    assumption = next(s for s in config["scenarios"] if s["name"] == view.scenario)
    details = (
        f"Scenario assumptions: ${assumption['commission']:.2f}/contract/fill commission; "
        f"${assumption['slippage']:.2f}/share/fill adverse price movement. "
        f"Price-reference coverage: {metadata['stock_start'][:10]} — {metadata['stock_end'][:10]}. "
        f"Completed LEAPS cycles: {metadata['leaps_cycles']}. "
        f"Requested dates: {metadata['requested_start'] or 'available start'} — "
        f"{metadata['requested_end'] or 'available end'}."
    )
    if "observed_date_coverage" in metadata:
        details += (
            f" Option quotes on {metadata['observed_stock_dates_with_options']}/{metadata['stock_quote_dates']} "
            f"observed stock dates ({metadata['observed_date_coverage']:.1%})."
        )
    else:
        details += " Option quote coverage unavailable: evaluating a previously saved trade result."
    chart = report.plot_dashboard().to_html(full_html=False, include_plotlyjs=True, config={"responsive": True})
    diagnostics = "".join(
        "<div class='plot-shell'><div class='plot-inner'>"
        + diagnostic_table(view, kind).to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
        + "</div></div>"
        for kind in ("segment", "year", "quarter")
    )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>PMCC evaluation</title><style>body{margin:24px auto;max-width:1440px;"
        "font:14px/1.5 Arial;color:#273345;padding:0 16px}"
        "header{max-width:1000px}li{margin:4px 0}.plot-shell{overflow-x:auto}.plot-inner{min-width:960px}"
        "</style></head><body><header><h1>PMCC research evaluation</h1>"
        f"<p>{html.escape(details)}</p><details open><summary>Interpretation and coverage</summary>"
        f"<ul>{notes}</ul></details></header>"
        f"<div class='plot-shell'><div class='plot-inner'>{chart}</div></div>{diagnostics}</body></html>"
    )
    path = Path(path).resolve()
    path.write_text(document, encoding="utf-8")
    return str(path)
