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

## How to write a NautilusTrader strategy

A strategy is a `Strategy` subclass paired with a frozen `StrategyConfig` subclass.
The engine drives it through a fixed lifecycle and a set of event callbacks; this
package follows the same shape for every strategy.

### 1. Config — a frozen msgspec struct

Subclass `nautilus_trader.config.StrategyConfig` (`frozen=True`). Strategy parameters
live here, **not** on the strategy instance. Keep numbers as `Decimal`, never float.

```python
from decimal import Decimal
from nautilus_trader.config import StrategyConfig

class PMCCConfig(StrategyConfig, frozen=True):
    underlying: str
    leaps_target_delta: Decimal = Decimal("0.80")
    short_target_delta: Decimal = Decimal("0.30")
    leaps_quantity: Decimal = Decimal("1")
```

### 2. Strategy — subclass `Strategy`, override the callbacks you need

`Strategy` extends `Actor`. Inherited from `Actor` are the **data** handlers
(`on_bar`, `on_quote_tick`, `on_option_chain`, `on_data`, `on_instrument`) and the
state handlers (`on_start`, `on_stop`, `on_reset`, `on_save`, `on_load`). `Strategy`
adds the **trading** handlers (`on_order_filled`, `on_position_opened`,
`on_position_changed`, `on_position_closed`) and the trading commands
(`submit_order`, `submit_order_list`, `cancel_order`, `modify_order`,
`close_position`).

```python
from nautilus_trader.model.data import Bar
from nautilus_trader.trading.strategy import Strategy
from trade_system_strategies.pmcc.config import PMCCConfig

class PMCCStrategy(Strategy):
    def __init__(self, config: PMCCConfig) -> None:
        super().__init__(config)          # self.config is now set
        self._config: PMCCConfig = config
        # mutable runtime state goes on self, NOT on the config

    def on_start(self) -> None:
        # subscribe to data; fetch instruments from self.cache
        self.subscribe_bars(...)

    def on_bar(self, bar: Bar) -> None:
        # decision logic; read indicators via .value, then act
        ...

    def on_order_filled(self, event) -> None:
        # reconcile each leg fill; for multi-leg combos route to a LegGroup
        ...
```

### Key conventions to follow

- **Lifecycle order**: the engine feeds registered indicators *before* your `on_*`
  handler runs, so `indicator.value` is current by the time `on_bar` fires.
- **Config vs state**: parameters on the frozen `StrategyConfig` (via `self.config`);
  mutable runtime state on `self`. Never mutate config.
- **Data access**: read instruments/orders/positions via `self.cache`
  (`self.cache.position(...)`, `self.cache.positions(instrument_id=...)`) and account
  exposure via `self.portfolio` (`is_flat`, `net_position`, `unrealized_pnl`). Do not
  hold your own copy of positions — query the cache.
- **Orders**: build with `self.order_factory` or construct directly, then
  `self.submit_order(order)`. For multi-leg combos there is no native client-side
  combo order in backtests — submit legs separately and reconcile via
  `shared.legs.LegGroup` in `on_order_filled`.
- **Indicators**: register in `on_start` with `self.register_indicator_for_bars(...)`
  so the base class feeds them automatically; read `indicator.value` / `.initialized`
  in `on_bar`.
- **Multiple instances**: each needs a unique `strategy_id` + `order_id_tag`
  (duplicate IDs raise at registration).
- **OMS**: `OmsType.NETTING` (one position per instrument) for netting strategies;
  `OmsType.HEDGING` (separate position per leg) when you need per-leg tracking. Set on
  the venue config.

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
