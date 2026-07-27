# trade-system

### Overview

Options backtesting strategies powered by [optopsy](https://github.com/michaeljohncarlos/optopsy) — a pandas-vectorized options backtesting engine.

### Workspace layout

This repository is a uv workspace. Packages live under `packages/`.

| Package | Description |
|---------|-------------|
| `options-strategies` | PMCC and other options strategies via optopsy |

### Development

```bash
uvx --from rust-just just init
uvx --from rust-just just lint
uvx --from rust-just just test-all
```

### Quick start — PMCC backtest

```bash
# 1. Download data (requires EODHD_API_KEY)
EODHD_API_KEY=... uv run optopsy-data download SPY        # options
uv run optopsy-data download SPY -s                       # stock OHLCV

# 2. Run backtest
uv run --all-packages python scripts/backtest_pmcc.py
```
