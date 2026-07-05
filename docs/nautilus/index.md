# NautilusTrader 指南

本部分文档讲解如何使用 NautilusTrader 框架开发和部署交易策略，聚焦于本仓库的两个主要交易场景：

- **Binance 比特币合约**（BTCUSDT-PERP）
- **IBKR 美股期权**（SPX/AAPL 期权链）

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [策略开发](strategy.md) | Strategy 类完整开发指南：配置、生命周期、数据处理、订单管理 |
| [实盘部署](deployment.md) | TradingNode 配置、Binance/IBKR 适配器、Docker、Kubernetes |

---

## 快速开始

### 回测

```python
from nautilus_trader.backtest.engine import BacktestEngine

engine = BacktestEngine()
engine.add_venue(...)
engine.add_instrument(instrument)
engine.add_data(bars)
engine.add_strategy(strategy)
engine.run()
```

### 实盘

```python
from nautilus_trader.live.node import TradingNode

node = TradingNode(config=config)
node.build()
node.trader.add_strategy(strategy)
node.run()
```

> **同一份策略代码，回测和实盘无需修改。**

---

## 本仓库策略

| 策略 | 适用场景 | 状态 |
|------|---------|------|
| RSI 双触 | Binance BTC 合约均值回归 | ✅ 完整 |
| PMCC | IBKR 美股期权 | 🏗️ 脚手架 |
| Backspread | IBKR 期权后价差 | 🏗️ 脚手架 |
