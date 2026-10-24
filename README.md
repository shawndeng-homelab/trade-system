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

### 蒙特卡洛合成行情

支持相关标的路径、美式有限差分期权定价及按日期注入冲击，输出可复现的日频 Parquet 数据集，供后续压力测试使用。

```bash
just sim-help
just sim-generate
just sim-validate
```

完整配置、Python 接口、存储恢复和模型假设见[合成行情数据源说明](docs/monte-carlo-data-source.md)。

### Quick start — PMCC backtest

```bash
# 1. Download data (requires EODHD_API_KEY)
EODHD_API_KEY=... uv run optopsy-data download SPY        # options
uv run optopsy-data download SPY -s                       # stock OHLCV

# 2. Run backtest
uv run --all-packages python scripts/backtest_pmcc.py
```
