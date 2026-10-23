"""Hand-calculated tests for fixed-fill PMCC research evaluation."""

from types import SimpleNamespace

import pandas as pd
import pytest
from options_strategies.evaluation import CostScenario
from options_strategies.evaluation import EvaluationConfig
from options_strategies.evaluation import EvaluationResult
from options_strategies.evaluation import build_pmcc_evaluation
from options_strategies.evaluation import evaluate_pmcc
from options_strategies.pmcc import PmccConfig


@pytest.fixture
def inputs():
    """Two trades spanning a quarter boundary with unequal contract quantities."""
    trades = pd.DataFrame(
        {
            "trade_id": [1, 1],
            "leg": ["leaps", "short_call"],
            "entry_date": pd.to_datetime(["2024-01-02", "2024-03-31"]),
            "exit_date": pd.to_datetime(["2024-04-02", "2024-04-01"]),
            "realized_pnl": [200.0, -20.0],
            "quantity": [2, 1],
            "multiplier": [100, 100],
            "exit_type": ["expiration", "stop_loss"],
        }
    )
    result = SimpleNamespace(trade_log=trades, summary={"total_return": 0.18}, equity_curve=pd.Series(dtype=float))
    stock = pd.DataFrame(
        {"quote_date": pd.date_range("2024-01-01", "2024-04-02"), "close": 100.0, "underlying_symbol": "SPY"}
    )
    return result, stock, PmccConfig(capital=1000)


def test_costs_units_and_leaps_control(inputs):
    """Commission is per contract; slippage additionally uses the price multiplier."""
    raw, stock, config = inputs
    original = raw.trade_log.copy(deep=True)
    evaluation = build_pmcc_evaluation(raw, stock, config)
    s = evaluation.summaries.set_index(["scenario", "strategy"])
    assert s.loc[("reference", "PMCC"), "commission"] == pytest.approx(3.9)
    assert s.loc[("reference", "PMCC"), "slippage"] == pytest.approx(6)
    assert s.loc[("reference", "PMCC"), "net_pnl"] == pytest.approx(170.1)
    assert s.loc[("ideal", "PMCC"), "net_pnl"] == 180
    assert s.loc[("reference", "PMCC"), "incremental_vs_leaps"] == pytest.approx(-23.3)
    assert s.loc[("reference", "LEAPS-only"), "net_pnl"] == pytest.approx(193.4)
    for scenario in evaluation.ledger.scenario.unique():
        ledger = evaluation.ledger[evaluation.ledger.scenario == scenario]
        actual = (
            ledger[(ledger.strategy == "PMCC") & (ledger.leg == "leaps")]
            .drop(columns="strategy")
            .reset_index(drop=True)
        )
        control = ledger[ledger.strategy == "LEAPS-only"].drop(columns="strategy").reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, control)
    assert (evaluation.summaries.baseline == 1000).all()
    pd.testing.assert_frame_equal(raw.trade_log, original)
    assert raw.summary == {"total_return": 0.18}


def test_costs_follow_event_dates_and_segments_reconcile(inputs):
    """Opening costs belong to Q1 even when both positions close in Q2."""
    evaluation = build_pmcc_evaluation(*inputs)
    parts = evaluation.segments.query("scenario == 'reference' and strategy == 'PMCC'")
    q = parts[parts.kind == "quarter"].set_index("label")
    assert q.loc["2024Q1", "net_pnl"] == pytest.approx(-4.95)
    assert q.loc["2024Q1", "total_trades"] == 0
    assert pd.isna(q.loc["2024Q1", "win_rate"])
    assert q.loc["2024Q2", "baseline"] == pytest.approx(995.05)
    assert q.loc["2024Q2", "net_pnl"] == pytest.approx(175.05)
    assert q.loc["2024Q2", "max_loss"] == pytest.approx(-23.3)
    for kind in ("year", "quarter", "segment"):
        assert parts.loc[parts.kind == kind, "net_pnl"].sum() == pytest.approx(170.1)
    assert len(parts[parts.kind == "segment"]) == 3


def test_no_trades_and_single_day():
    """No trades produce flat cash, no invented ratios, and nonempty windows only."""
    raw = SimpleNamespace(trade_log=pd.DataFrame())
    stock = pd.DataFrame({"quote_date": pd.to_datetime(["2024-01-02"]), "close": [100.0]})
    evaluation = build_pmcc_evaluation(raw, stock, PmccConfig(capital=1000))
    assert evaluation.ledger.empty
    assert (evaluation.curves.equity == 1000).all()
    assert (evaluation.summaries.total_trades == 0).all()
    assert evaluation.summaries.win_rate.isna().all()
    assert evaluation.summaries.annualized_return.isna().all()
    assert len(evaluation.segments) == 3 * 2 * 3


def test_negative_equity_is_reported_not_truncated(inputs):
    """Post-trade stress costs are not an executable insolvency model."""
    raw, stock, config = inputs
    scenarios = EvaluationConfig(
        scenarios=(CostScenario(name="huge", commission=1000, slippage=0),), primary_scenario="huge"
    )
    evaluation = build_pmcc_evaluation(raw, stock, config, scenarios)
    assert evaluation.summaries.capital_insufficient.all()
    assert evaluation.curves.equity.min() < 0
    assert evaluation.summaries.annualized_return.isna().all()
    assert len(evaluation.trades) == 2


def test_storage_roundtrip_and_no_overwrite(inputs, tmp_path):
    """All research tables and raw trade records round-trip without pickle."""
    evaluation = build_pmcc_evaluation(*inputs)
    path = tmp_path / "run"
    evaluation.save(path)
    restored = EvaluationResult.load(path)
    for field in ("trades", "ledger", "curves", "summaries", "segments"):
        pd.testing.assert_frame_equal(getattr(evaluation, field), getattr(restored, field))
    pd.testing.assert_series_equal(evaluation.stock_prices, restored.stock_prices, check_names=False)
    pd.testing.assert_frame_equal(evaluation.raw_result.trade_log, restored.raw_result.trade_log)
    assert restored.metadata == evaluation.metadata
    with pytest.raises(FileExistsError):
        evaluation.save(path)
    assert not list(path.glob("*.pkl"))


def test_numeric_results_repeat_and_fingerprints_change(inputs):
    """Identical inputs give identical numbers; input changes are identifiable."""
    first = build_pmcc_evaluation(*inputs)
    second = build_pmcc_evaluation(*inputs)
    pd.testing.assert_frame_equal(first.summaries, second.summaries)
    assert first.metadata["input_fingerprints"] == second.metadata["input_fingerprints"]
    raw, stock, config = inputs
    changed = stock.copy()
    changed.loc[0, "close"] = 101
    third = build_pmcc_evaluation(raw, changed, config)
    assert third.metadata["input_fingerprints"]["stock"] != first.metadata["input_fingerprints"]["stock"]


def test_public_runner_filters_dates_and_runs_engine_once(inputs, monkeypatch):
    """Input boundaries are applied before the one engine call; controls reuse fills."""
    raw, stock, config = inputs
    calls = []

    def fake_run(options, stocks, config):
        calls.append((options, stocks))
        return raw

    monkeypatch.setattr("options_strategies.evaluation.core.run_pmcc", fake_run)
    options = stock.copy()
    options["expiration_type"] = "monthly"
    evaluation = evaluate_pmcc(options, stock, config)
    assert len(calls) == 1
    assert evaluation.metadata["option_rows"] == len(options)
    assert "options" in evaluation.metadata["input_fingerprints"]
    assert evaluation.metadata["requested_start"] is None


@pytest.mark.parametrize("kwargs", [{"scenarios": ()}, {"primary_scenario": "missing"}, {"time_segments": 0}])
def test_config_rejects_invalid_experiments(kwargs):
    """Invalid research settings fail before execution."""
    with pytest.raises(ValueError):
        EvaluationConfig(**kwargs)


def test_duplicate_scenarios_and_invalid_costs():
    """Scenario keys and monetary inputs must be unambiguous and finite."""
    with pytest.raises(ValueError):
        EvaluationConfig(scenarios=(CostScenario(name="reference", commission=0, slippage=0),) * 2)
    for cost in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            CostScenario(name="bad", commission=cost, slippage=0)


def test_scoped_diagnostics_reconcile_to_the_window(inputs):
    """A new scope gets fresh calendar buckets and the correct pre-window baseline."""
    evaluation = build_pmcc_evaluation(*inputs)
    scoped = evaluation.diagnostics(start="2024-03-01", end="2024-04-02")
    pmcc = scoped[(scoped.strategy == "PMCC") & (scoped.kind == "segment")]
    assert pmcc.iloc[0].baseline == pytest.approx(996.7)
    assert pmcc.net_pnl.sum() == pytest.approx(173.4)
    assert pmcc.start.min() == pd.Timestamp("2024-03-01")
    assert pmcc.end.max() == pd.Timestamp("2024-04-02")
    with pytest.raises(ValueError, match="within"):
        evaluation.diagnostics(start="2023-01-01")


def test_snapshot_does_not_alias_raw_result(inputs):
    """Subsequent caller edits cannot rewrite the raw evidence saved with a run."""
    evaluation = build_pmcc_evaluation(*inputs)
    inputs[0].trade_log.loc[0, "realized_pnl"] = 999
    assert evaluation.raw_result.trade_log.loc[0, "realized_pnl"] == 200


def test_runner_applies_requested_dates_before_execution(inputs, monkeypatch):
    """No future rows enter a requested subperiod's engine call."""
    _, stock, _ = inputs
    config = PmccConfig(start_date="2024-03-01", end_date="2024-03-10", capital=1000)
    options = stock.assign(expiration_type="monthly")
    seen = []

    def engine(options, stock, config):
        seen.append((options.copy(), stock.copy()))
        return SimpleNamespace(trade_log=pd.DataFrame())

    monkeypatch.setattr("options_strategies.evaluation.core.run_pmcc", engine)
    evaluation = evaluate_pmcc(options, stock, config)
    assert len(seen) == 1
    for frame in seen[0]:
        assert frame.quote_date.min() == pd.Timestamp("2024-03-01")
        assert frame.quote_date.max() == pd.Timestamp("2024-03-10")
    assert evaluation.metadata["observed_date_coverage"] == 1
    assert evaluation.metadata["requested_end"] == "2024-03-10"


def test_filter_without_option_coverage_is_not_a_flat_valid_backtest(inputs, monkeypatch):
    """No monthly quotes must fail instead of producing a misleading empty result."""
    _, stock, config = inputs
    options = stock.assign(expiration_type="weekly")
    monkeypatch.setattr("options_strategies.evaluation.core.run_pmcc", lambda *args: pytest.fail("engine must not run"))
    with pytest.raises(ValueError, match="cover"):
        evaluate_pmcc(options, stock, config)


def test_storage_rejects_unknown_version(inputs, tmp_path):
    """Future or corrupt manifests are not interpreted with the current schema."""
    evaluation = build_pmcc_evaluation(*inputs)
    path = tmp_path / "run"
    evaluation.save(path)
    manifest = path / "manifest.json"
    manifest.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="schema"):
        EvaluationResult.load(path)
