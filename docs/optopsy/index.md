# optopsy 回测引擎

本仓库使用 [optopsy](https://github.com/michaeljohncarlos/optopsy) 作为期权回测后端，替代了原先的 NautilusTrader 事件驱动引擎。

---

## 为什么选择 optopsy

| 维度 | NautilusTrader | optopsy |
|------|---------------|---------|
| 范式 | 事件驱动 (`on_bar`/`submit_order`) | Pandas 矢量化 |
| 速度 | 逐 bar 推进，慢 | 全量向量化计算，快 |
| 期权支持 | 需手动管理腿/行权 | 内置 delta targeting、DTE 筛选、take_profit |
| 数据 | 需自建 catalog | 内置 EODHD + yfinance 缓存 |
| 实盘 | ✅ 支持 | ❌ 纯回测 |

optopsy 的矢量化范式天然适合期权策略的参数扫描和快速迭代。

---

## 核心概念

### 策略函数

optopsy 的策略是纯函数，返回 entry/exit 规则：

```python
import optopsy as op

# 单腿策略
op.long_calls(data, raw=True, leg1_delta=..., max_entry_dte=..., exit_dte=...)
op.short_calls(data, raw=True, leg1_delta=..., take_profit=0.8, ...)
```

### TargetRange — 参数范围

```python
from optopsy.types import TargetRange

delta = TargetRange(target=0.80, min=0.75, max=0.85)
# target 必须在 [min, max] 区间内
```

### 信号 — entry_dates

optopsy 信号是无状态的 per-bar 布尔谓词，通过 `signal_dates()` 转换为 `(underlying_symbol, quote_date)` DataFrame：

```python
sig = op.signal(op.iv_rank_above(50))
entry_dates = op.signal_dates(stock_df, sig)
```

信号可组合：`sig1 & sig2`（AND）、`sig1 | sig2`（OR）。

### 模拟器

```python
# 单策略
result = op.simulate(data, strategy, capital=100_000, max_positions=1, **kwargs)
# result: SimulationResult(trade_log, equity_curve, summary)

# 多腿组合
result = op.simulate_portfolio(
    legs=[
        {"data": df, "strategy": op.long_calls, "weight": 0.6, "name": "leaps", ...},
        {"data": df, "strategy": op.short_calls, "weight": 0.4, "name": "short_call", ...},
    ],
    capital=100_000,
)
# result: PortfolioResult(summary, trade_log, equity_curve, leg_results)
```

### take_profit 语义

对 short call：`_unrealized_pct = (entry - mid) / entry`。当 short call 价格跌到 entry 的 20% 时，pct = 0.8，触发 `take_profit=0.8`（赚 80% 平仓）。

---

## 数据

optopsy 内置 EODHD（期权）+ yfinance（股票）数据缓存：

```bash
# 下载期权数据（需要 EODHD_API_KEY）
EODHD_API_KEY=... optopsy-data download SPY

# 下载股票数据
optopsy-data download SPY -s
```

EODHD 提供约 730 天的期权历史数据。

---

## 本仓库策略

| 策略 | 位置 | 说明 | 状态 |
|------|------|------|------|
| PMCC | `pmcc/` | 穷人备兑：long LEAPS + short near-term call | ✅ 可运行 |

策略结构：`config.py`（PmccConfig）· `signals.py`（entry_dates 生成）· `strategy.py`（simulate_portfolio 调度）。
