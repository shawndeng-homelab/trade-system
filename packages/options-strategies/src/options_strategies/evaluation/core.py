"""PMCC controls, event costs and descriptive time-segment diagnostics."""

import hashlib
import importlib.metadata
import math
import platform
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from options_strategies.evaluation.config import EvaluationConfig
from options_strategies.pmcc.config import PmccConfig
from options_strategies.pmcc.strategy import run_pmcc


LIMITATIONS = [
    "Realized equity only; open-position gains and losses are not valued.",
    "Only completed trades returned by the engine are observable; open or rejected trades and their costs are unknown.",
    "Costs are applied to fixed fills after simulation; selection, exits and buying power are not re-simulated.",
    "PMCC legs remain independent; this evaluation does not enforce short-call coverage or capital constraints.",
    "Time segments are descriptive diagnostics, not independent out-of-sample validation.",
    "Stock prices are a price reference, not a verified dividend-reinvested total-return benchmark.",
    "Cash is a zero-return control, not historical risk-free interest.",
]


@dataclass(frozen=True)
class EvaluationResult:
    """Engine result and portable research tables consumed without engine coupling."""

    raw_result: object
    trades: pd.DataFrame
    ledger: pd.DataFrame
    curves: pd.DataFrame
    summaries: pd.DataFrame
    segments: pd.DataFrame
    stock_prices: pd.Series
    metadata: dict

    def diagnostics(self, scenario=None, *, start=None, end=None) -> pd.DataFrame:
        """Recalculate year, quarter and equal-time diagnostics for a chosen scope."""
        scenario = scenario or self.metadata["evaluation_config"]["primary_scenario"]
        if scenario not in self.curves.scenario.unique():
            raise ValueError(f"Unknown scenario: {scenario}")
        start = pd.Timestamp(start if start is not None else self.metadata["start"])
        end = pd.Timestamp(end if end is not None else self.metadata["end"])
        if start > end or start < pd.Timestamp(self.metadata["start"]) or end > pd.Timestamp(self.metadata["end"]):
            raise ValueError("Diagnostics must be within the evaluation interval")
        rows = []
        for strategy in ("PMCC", "LEAPS-only"):
            curve = self.curves[(self.curves.scenario == scenario) & (self.curves.strategy == strategy)]
            curve = curve.set_index("date").equity
            events = self.ledger[(self.ledger.scenario == scenario) & (self.ledger.strategy == strategy)]
            trades = self.trades if strategy == "PMCC" else self.trades[self.trades.leg == "leaps"]
            for kind, label, left, right in _windows(start, end, self.metadata["evaluation_config"]["time_segments"]):
                rows.append(
                    {
                        "scenario": scenario,
                        "strategy": strategy,
                        "kind": kind,
                        "label": label,
                        **_summarize(events, trades, curve, self.metadata["capital"], left, right),
                    }
                )
        return _add_contribution(pd.DataFrame(rows))

    def save(self, path: str | Path) -> str:
        """Save JSON metadata and Parquet tables for offline report reconstruction."""
        from options_strategies.evaluation.storage import save_evaluation  # noqa: PLC0415

        return save_evaluation(self, path)

    @classmethod
    def load(cls, path: str | Path) -> "EvaluationResult":
        """Read a saved evaluation without re-running the strategy."""
        from options_strategies.evaluation.storage import load_evaluation  # noqa: PLC0415

        return load_evaluation(path)


def _add_contribution(frame):
    keys = [key for key in ("scenario", "kind", "label", "start", "end") if key in frame]
    control = frame[frame.strategy == "LEAPS-only"][[*keys, "net_pnl"]].rename(columns={"net_pnl": "_leaps_net"})
    frame = frame.merge(control, on=keys, how="left", validate="many_to_one")
    frame["incremental_vs_leaps"] = (frame.net_pnl - frame._leaps_net).where(frame.strategy == "PMCC")
    return frame.drop(columns="_leaps_net")


def _fingerprint(frame: pd.DataFrame) -> str:
    schema = repr([(str(column), str(dtype)) for column, dtype in frame.dtypes.items()])
    digest = hashlib.sha256(schema.encode())
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()


def _provenance() -> dict:
    versions = {"python": platform.python_version()}
    for name in (
        "options-strategies",
        "backtest-charts",
        "optopsy",
        "pandas",
        "plotly",
        "numpy",
        "pyarrow",
        "pydantic",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    git = {"commit": None, "dirty": None, "diff_sha256": None}
    root = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), None)
    if root:
        try:

            def read(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)

            git = {
                "commit": read("rev-parse", "HEAD").decode().strip(),
                "dirty": bool(read("status", "--porcelain")),
                "diff_sha256": hashlib.sha256(read("diff", "HEAD")).hexdigest(),
            }
        except (OSError, subprocess.CalledProcessError):
            pass
    # Include uncommitted/untracked implementation content in reproducibility metadata.
    sources = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        sources.update(str(path.relative_to(Path(__file__).resolve().parents[1])).encode())
        sources.update(path.read_bytes())
    return {"versions": versions, "git": git, "strategy_source_sha256": sources.hexdigest()}


def _curve_stats(curve: pd.Series, baseline: float, start, end) -> dict:
    peaks = curve.cummax().clip(lower=max(baseline, 0))
    dd = (curve / peaks.where(peaks > 0) - 1).min()
    ret = float(curve.iloc[-1] / baseline - 1) if baseline > 0 else None
    years = (end - start).days / 365.25
    annualized = None
    if ret is not None and ret >= -1 and years > 0:
        try:
            value = (1 + ret) ** (1 / years) - 1
            if math.isfinite(value):
                annualized = value
        except OverflowError:
            pass
    return {
        "total_return": ret,
        "annualized_return": annualized,
        "max_drawdown": float(dd) if pd.notna(dd) else None,
        "capital_insufficient": bool((curve <= 0).any() or baseline <= 0),
    }


def _windows(start, end, count):
    days = pd.date_range(start, end, freq="D")
    for frequency, kind in (("Y", "year"), ("Q", "quarter")):
        for period in days.to_period(frequency).unique():
            yield kind, str(period), max(start, period.start_time.normalize()), min(end, period.end_time.normalize())
    # Adjacent, disjoint calendar-day buckets. Tiny windows have fewer nonempty buckets.
    for i in range(min(count, len(days))):
        n = min(count, len(days))
        yield "segment", f"Segment {i + 1}", days[i * len(days) // n], days[(i + 1) * len(days) // n - 1]


def _summarize(events, trades, curve, capital, start, end):
    selected = events[events.date.between(start, end)]
    before = events.loc[events.date < start, "net_pnl"].sum()
    baseline = capital + float(before)
    window_curve = curve.loc[start:end]
    closed = trades[trades.exit_date.between(start, end)]
    # Full round-trip trade net P&L is for trade statistics only; period P&L uses event dates.
    per_trade = events.groupby("trade_key").net_pnl.sum().reindex(closed.trade_key)
    winners = per_trade[per_trade > 0]
    net = float(selected.net_pnl.sum())
    return {
        "start": start,
        "end": end,
        "baseline": baseline,
        "gross_pnl": float(selected.gross_pnl.sum()),
        "commission": float(selected.commission.sum()),
        "slippage": float(selected.slippage.sum()),
        "net_pnl": net,
        "total_trades": len(closed),
        "win_rate": float((per_trade > 0).mean()) if len(closed) else None,
        "max_loss": float(min(per_trade.min(), 0)) if len(closed) else None,
        "top5_profit_share": float(winners.nlargest(5).sum() / winners.sum()) if len(winners) else None,
        **_curve_stats(window_curve, baseline, start, end),
    }


def build_pmcc_evaluation(result, stock_df, config: PmccConfig, evaluation_config=None, *, start=None, end=None):
    """Evaluate completed PMCC fills; also supports previously saved engine results.

    Explicit boundaries must contain the trades. Use the report comparison view
    for shorter observation windows, rather than silently dropping crossing trades.
    """
    evaluation_config = evaluation_config or EvaluationConfig()
    trades = result.trade_log.copy(deep=True)
    required = ["entry_date", "exit_date", "realized_pnl", "leg"]
    if trades.empty:
        for column in required:
            trades[column] = pd.Series(dtype="object")
    missing = set(required) - set(trades)
    if missing:
        raise ValueError(f"Trade log missing columns: {sorted(missing)}")
    for column in ("entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column]).dt.normalize()
        if trades[column].isna().any():
            raise ValueError(f"Missing {column} in completed trades")
    if (trades.exit_date < trades.entry_date).any():
        raise ValueError("Trade exits must not precede entries")
    if not trades.empty and not set(trades.leg).issubset({"leaps", "short_call"}):
        raise ValueError("PMCC evaluation requires legs named 'leaps' and 'short_call'")
    trades = trades.sort_values(["exit_date", "entry_date", "leg"], kind="stable").reset_index(drop=True)
    trades["trade_key"] = range(len(trades))
    for column, default in (("quantity", config.quantity), ("multiplier", config.multiplier)):
        trades[column] = trades.get(column, default)
        if not trades.empty and (not trades[column].map(math.isfinite).all() or (trades[column] <= 0).any()):
            raise ValueError(f"{column} must be finite and positive")
    if not trades.realized_pnl.map(math.isfinite).all():
        raise ValueError("Trade P&L must be finite")
    stock = stock_df.copy()
    if "underlying_symbol" in stock:
        stock = stock[stock.underlying_symbol == config.symbol]
    stock["quote_date"] = pd.to_datetime(stock["quote_date"]).dt.normalize()
    prices = stock.sort_values("quote_date").groupby("quote_date").close.last().astype(float)
    if prices.empty:
        raise ValueError("Stock data must contain the configured symbol")
    start = pd.Timestamp(
        start
        or config.start_date
        or min(prices.index.min(), trades.entry_date.min() if len(trades) else prices.index.min())
    ).normalize()
    end = pd.Timestamp(
        end or config.end_date or max(prices.index.max(), trades.exit_date.max() if len(trades) else prices.index.max())
    ).normalize()
    if start > end:
        raise ValueError("Evaluation start must not follow end")
    if len(trades) and ((trades.entry_date < start).any() or (trades.exit_date > end).any()):
        raise ValueError("Evaluation boundaries must contain all completed trades")
    capital = float(config.capital)
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("Capital must be finite and positive")
    prices = prices.loc[start:end]
    if prices.empty or not prices.map(math.isfinite).all() or (prices <= 0).any():
        raise ValueError("Price reference needs finite positive prices within the evaluation interval")

    rows = []
    for scenario in evaluation_config.scenarios:
        for strategy in ("PMCC", "LEAPS-only"):
            selected = trades if strategy == "PMCC" else trades[trades.leg == "leaps"]
            for trade in selected.itertuples():
                commission = float(trade.quantity * scenario.commission)
                slippage = float(trade.quantity * trade.multiplier * scenario.slippage)
                for event, date, pnl in (
                    ("entry", trade.entry_date, 0.0),
                    ("exit", trade.exit_date, trade.realized_pnl),
                ):
                    rows.append(
                        {
                            "scenario": scenario.name,
                            "strategy": strategy,
                            "trade_key": trade.trade_key,
                            "leg": trade.leg,
                            "date": date,
                            "event": event,
                            "gross_pnl": float(pnl),
                            "commission": commission,
                            "slippage": slippage,
                            "net_pnl": float(pnl - commission - slippage),
                        }
                    )
    columns = [
        "scenario",
        "strategy",
        "trade_key",
        "leg",
        "date",
        "event",
        "gross_pnl",
        "commission",
        "slippage",
        "net_pnl",
    ]
    ledger = pd.DataFrame(rows, columns=columns)
    ledger["date"] = pd.to_datetime(ledger.date)
    for column in ("gross_pnl", "commission", "slippage", "net_pnl"):
        ledger[column] = ledger[column].astype(float)
    curves, summaries, segments = [], [], []
    dates = pd.date_range(start, end, freq="D")
    for scenario in evaluation_config.scenarios:
        for strategy in ("PMCC", "LEAPS-only"):
            events = ledger[(ledger.scenario == scenario.name) & (ledger.strategy == strategy)]
            pnl = events.groupby("date").net_pnl.sum().reindex(dates, fill_value=0)
            curve = capital + pnl.cumsum()
            curve_frame = curve.rename("equity").rename_axis("date").reset_index()
            curve_frame["scenario"], curve_frame["strategy"] = scenario.name, strategy
            curves.append(curve_frame)
            selected = trades if strategy == "PMCC" else trades[trades.leg == "leaps"]
            common = {"scenario": scenario.name, "strategy": strategy}
            summaries.append({**common, **_summarize(events, selected, curve, capital, start, end)})
            for kind, label, left, right in _windows(start, end, evaluation_config.time_segments):
                segments.append(
                    {
                        **common,
                        "kind": kind,
                        "label": label,
                        **_summarize(events, selected, curve, capital, left, right),
                    }
                )
    metadata = {
        "schema_version": 1,
        "strategy_config": config.model_dump(mode="json"),
        "evaluation_config": evaluation_config.model_dump(mode="json"),
        "capital": capital,
        "symbol": config.symbol,
        "requested_start": config.start_date,
        "requested_end": config.end_date,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "stock_start": prices.index.min().isoformat(),
        "stock_end": prices.index.max().isoformat(),
        "trade_count": len(trades),
        "leaps_cycles": int((trades.leg == "leaps").sum()),
        "input_fingerprints": {"stock": _fingerprint(stock_df), "trade_log": _fingerprint(result.trade_log)},
        "limitations": list(LIMITATIONS),
        **_provenance(),
    }
    return EvaluationResult(
        deepcopy(result),
        trades,
        ledger,
        pd.concat(curves, ignore_index=True),
        _add_contribution(pd.DataFrame(summaries)),
        _add_contribution(pd.DataFrame(segments)),
        prices,
        metadata,
    )


def evaluate_pmcc(options_df, stock_df, config: PmccConfig, evaluation_config=None) -> EvaluationResult:
    """Run PMCC once on the available requested interval, then derive controls."""
    options, stock = options_df.copy(), stock_df.copy()
    for frame in (options, stock):
        frame["quote_date"] = pd.to_datetime(frame["quote_date"]).dt.normalize()
    if "underlying_symbol" in options:
        options = options[options.underlying_symbol == config.symbol]
    if "underlying_symbol" in stock:
        stock = stock[stock.underlying_symbol == config.symbol]
    if config.expiration_type and "expiration_type" in options:
        options = options[options.expiration_type.str.lower() == config.expiration_type.lower()]
    if options.empty or stock.empty:
        raise ValueError("Option and stock data must cover the configured symbol")
    start = max(
        options.quote_date.min(),
        stock.quote_date.min(),
        pd.Timestamp(config.start_date) if config.start_date else options.quote_date.min(),
    )
    end = min(
        options.quote_date.max(),
        stock.quote_date.max(),
        pd.Timestamp(config.end_date) if config.end_date else options.quote_date.max(),
    )
    if start > end:
        raise ValueError("Requested interval has no common option and stock coverage")
    options = options[options.quote_date.between(start, end)]
    stock = stock[stock.quote_date.between(start, end)]
    result = run_pmcc(options, stock, config)
    evaluation = build_pmcc_evaluation(result, stock, config, evaluation_config, start=start, end=end)
    evaluation.metadata["input_fingerprints"].update({"options": _fingerprint(options), "stock": _fingerprint(stock)})
    evaluation.metadata["option_rows"] = len(options)
    evaluation.metadata["option_quote_dates"] = int(options.quote_date.nunique())
    evaluation.metadata["stock_quote_dates"] = int(stock.quote_date.nunique())
    observed_dates = set(stock.quote_date)
    evaluation.metadata["observed_stock_dates_with_options"] = len(observed_dates & set(options.quote_date))
    evaluation.metadata["observed_date_coverage"] = len(observed_dates & set(options.quote_date)) / len(observed_dates)
    return evaluation
