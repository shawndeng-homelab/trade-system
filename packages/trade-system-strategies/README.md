# trade-system-strategies

NautilusTrader trading strategies — PMCC (Poor Man's Covered Call) and call
backspread — with shared tooling and a Jupyter research layer.

## Layout

- `shared/` — strategy-agnostic, engine-free tooling: multi-leg state machine,
  greeks helpers, option-leg selection, catalog IO. Pure functions, usable in
  notebooks and backtests alike.
- `pmcc/`, `backspread/` — each strategy is self-contained: `config.py`
  (`StrategyConfig` subclass), `strategy.py` (`Strategy` subclass), `signals.py`
  (strategy-specific leg-selection logic as pure functions).
- `research/` — Jupyter-friendly analysis helpers and jupytext notebooks.

## Strategy registration

Low-level (script/debug):

```python
from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.strategy import PMCCStrategy

engine.add_strategy(PMCCStrategy(PMCCConfig(underlying="SPY", ...)))
```

High-level (`BacktestNode` / parameter sweeps):

```python
from nautilus_trader.config import ImportableStrategyConfig

ImportableStrategyConfig(
    strategy_path="trade_system_strategies.pmcc.strategy:PMCCStrategy",
    config_path="trade_system_strategies.pmcc.config:PMCCConfig",
    config={"underlying": "SPY", ...},
)
```

## Research

Install the optional research stack and open notebooks:

```bash
uv sync --all-packages --all-groups --extra research
```
