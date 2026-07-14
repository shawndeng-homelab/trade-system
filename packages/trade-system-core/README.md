# trade-system-core

Unified runner for backtest and live trading with OpenTelemetry observability.

## Features

- **YAML-driven configuration** — declare venues, data sources, strategies, and observability in a single config file
- **CLI entry point** — `trade-system backtest`, `trade-system live`, `trade-system run`
- **Backtest runner** — `run_backtest()` from a `RunConfig` for full control
- **Live trading** — `run_live()` with pluggable data/execution adapters
- **Dry-run mode** — `--dry-run` for simulated trading with real data
- **Slippage & latency models** — configurable fill model and latency model per venue
- **Fee model registry** — IBKR tiered/fixed, Binance spot, extensible via `AdapterRegistry`
- **OTel instrumentation** — `InstrumentedStrategy` mixin auto-emits spans and metrics

## Quick Start

### CLI

```bash
# Backtest from YAML config
uv run --all-packages trade-system backtest configs/rsi_backtest.yaml

# Live trading
uv run --all-packages trade-system live configs/live.yaml

# Paper trading (real data, SIM execution)
uv run --all-packages trade-system live configs/live.yaml --dry-run

# Auto-detect mode from config
uv run --all-packages trade-system run configs/rsi_backtest.yaml
```

### Python API

```python
from trade_system_core import run_backtest
from trade_system_core.config import load_config

# Run from a YAML config
config = load_config("configs/rsi_backtest.yaml")
results = run_backtest(config, tearsheet=True)
```

For simple single-strategy backtests or multi-venue setups, use NautilusTrader's
`BacktestEngine` directly — see `scripts/backtest_rsi.py` and `scripts/backtest_pmcc.py`
for examples.

### OTel Instrumentation

```python
from trade_system_core.telemetry import InstrumentedStrategy

class RsiStrategy(InstrumentedStrategy):
    # Automatically emits spans and metrics on on_bar, on_fill, etc.
    ...
```

## YAML Configuration

### Backtest (IBKR data + slippage)

```yaml
mode: backtest
trader_id: "RSI-BACKTEST-001"
venues:
  - name: ARCA
    oms_type: NETTING
    account_type: MARGIN
    starting_balances: ["10_000 USD"]
    fee_model: ibkr_tiered
    fill_model:
      fill_model_path: "nautilus_trader.backtest.models.fill:ProbabilisticFillModel"
      config_path: "nautilus_trader.backtest.config:ProbabilisticFillModelConfig"
      config:
        prob_fill_on_limit: 0.9
        prob_slippage: 0.05
data:
  - catalog_path: "."
    instrument_id: SPY.ARCA
    bar_type: "SPY.ARCA-1-MINUTE-LAST-EXTERNAL"
    start_time: "2026-01-02T00:00:00+00:00"
    end_time: "2026-06-30T00:00:00+00:00"
strategies:
  - strategy_path: "trade_system_strategies.rsi.strategy:RsiStrategy"
    config_path: "trade_system_strategies.rsi.config:RsiConfig"
    config:
      instrument_id: SPY.ARCA
      rsi_period: 14
```

### Live (Massive data + Binance execution)

```yaml
mode: live
trader_id: "RSI-LIVE-001"
venues:
  - name: BINANCE
    oms_type: NETTING
    account_type: MARGIN
    exec_client: BINANCE
data_clients:
  MASSIVE:
    api_key: null  # reads MASSIVE_API_KEY env var
exec_clients:
  BINANCE:
    api_key: null
data:
  - instrument_id: "BTC/USDT.BINANCE"
    bar_type: "BTC/USDT.BINANCE-1-HOUR-LAST-EXTERNAL"
    data_client: MASSIVE
strategies:
  - strategy_path: "trade_system_strategies.rsi.strategy:RsiStrategy"
    config_path: "trade_system_strategies.rsi.config:RsiConfig"
    config:
      instrument_id: "BTC/USDT.BINANCE"
observability:
  enabled: true
  otlp_endpoint: "http://localhost:4317"
```

## Adapter Registry

Data sources and execution clients are registered by name. Built-in adapters:

| Name | Type | Package |
|------|------|---------|
| `MASSIVE` | data client | `trade-system-massive` |
| `IBKR` | data + exec client | `nautilus-trader[ib]` |
| `BINANCE` | data + exec client | `nautilus-trader` |
| `ibkr_tiered` | fee model | `trade-system-venues` |
| `binance_spot` | fee model | `trade-system-venues` |

Register custom adapters:

```python
from trade_system_core import get_registry

registry = get_registry()
registry.register_data_client("MY_ADAPTER", MyDataClientFactory)
registry.register_fee_model("my_fee", MyFeeModel)
```

## Docker

```bash
docker build -t trade-system .
docker run -v $(pwd)/config.yaml:/etc/trade-system/config.yaml trade-system backtest /etc/trade-system/config.yaml
docker run -v $(pwd)/config.yaml:/etc/trade-system/config.yaml trade-system live /etc/trade-system/config.yaml
docker run -v $(pwd)/config.yaml:/etc/trade-system/config.yaml trade-system live /etc/trade-system/config.yaml --dry-run
```
