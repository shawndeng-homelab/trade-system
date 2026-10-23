"""Regressions for realized drawdown and calendar entry signals."""

import importlib

import pandas as pd
import pytest
from options_strategies.pmcc.signals import short_call_entry_dates
from options_strategies.shared.results import correct_drawdown
from optopsy.simulator import PortfolioResult
from optopsy.simulator import SimulationResult


def test_weekly_signal_uses_iso_year():
    """One ISO week crossing New Year has one entry per underlying."""
    stock = pd.DataFrame(
        {
            "underlying_symbol": ["SPY"] * 4,
            "quote_date": pd.to_datetime(["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-06"]),
        }
    )
    assert short_call_entry_dates(stock).quote_date.tolist() == list(pd.to_datetime(["2024-12-30", "2025-01-06"]))


def test_first_loss_corrected_for_portfolio_and_leg_without_mutation():
    """Portfolio and per-leg summaries include losses relative to starting cash."""
    log = pd.DataFrame(
        {
            "exit_date": pd.to_datetime(["2025-01-02"]),
            "realized_pnl": [-100.0],
            "equity": [900.0],
            "cumulative_pnl": [-100.0],
        }
    )
    equity = pd.Series([900.0], index=log.exit_date)
    leg = SimulationResult(log, equity, {"max_drawdown": 0.0})
    result = PortfolioResult(log, equity, {"max_drawdown": 0.0}, {"leg": leg})
    corrected = correct_drawdown(result, 1000)
    assert corrected.summary["max_drawdown"] == pytest.approx(-0.1)
    assert corrected.leg_results["leg"].summary["max_drawdown"] == pytest.approx(-0.1)
    assert result.summary["max_drawdown"] == leg.summary["max_drawdown"] == 0


def test_same_day_exits_use_daily_close_not_arbitrary_trade_order():
    """Opposing exits on a day do not manufacture intraday drawdown."""
    log = pd.DataFrame({"exit_date": ["2025-01-02"] * 2, "realized_pnl": [-100, 100]})
    result = SimulationResult(log, pd.Series(dtype=float), {"max_drawdown": -0.1})
    assert correct_drawdown(result, 1000).summary["max_drawdown"] == 0


@pytest.mark.parametrize("strategy_name", ["pmcc", "benchmark", "odte_iron_condor"])
def test_strategy_entrypoints_correct_engine_drawdown(strategy_name, monkeypatch):
    """Every public runner applies the correction to the actual engine return."""
    module = importlib.import_module(f"options_strategies.{strategy_name}.strategy")
    config_module = importlib.import_module(f"options_strategies.{strategy_name}.config")
    config_name = {"pmcc": "PmccConfig", "benchmark": "BenchmarkConfig", "odte_iron_condor": "OdteIronCondorConfig"}
    config_type = getattr(config_module, config_name[strategy_name])
    kwargs = {"capital": 1000}
    if strategy_name != "pmcc":
        kwargs["symbols"] = ["SPY"]
    config = config_type(**kwargs)
    log = pd.DataFrame({"exit_date": ["2025-01-02"], "realized_pnl": [-100]})
    upstream = PortfolioResult(log, pd.Series(dtype=float), {"max_drawdown": 0}, {})
    monkeypatch.setattr(module.op, "simulate_portfolio", lambda *args, **kwargs: upstream)
    stock = pd.DataFrame({"underlying_symbol": ["SPY"], "quote_date": pd.to_datetime(["2025-01-01"])})
    options = pd.DataFrame()
    if strategy_name != "pmcc":
        stock, options = {"SPY": stock}, {"SPY": options}
    result = getattr(module, f"run_{strategy_name}")(options, stock, config)
    assert result.summary["max_drawdown"] == pytest.approx(-0.1)
    assert upstream.summary["max_drawdown"] == 0
