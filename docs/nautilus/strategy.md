# NautilusTrader 策略开发指南

本文档讲解如何通过 `nautilus_trader.trading.strategy.Strategy` 实现交易策略。本仓库主要交易 **比特币（Binance）** 和 **IBKR（Interactive Brokers）**，示例和配置均围绕这两个场景。

---

## 1. 概述

`Strategy` 继承自 `Actor`，在数据/事件处理能力之上增加了**订单管理**能力。

**核心能力：** 历史数据请求 · 实时数据订阅 · 时间警报/定时器 · 缓存访问 · 投资组合访问 · 订单与持仓管理

**关键理念：** 同一份策略代码既可用于回测，也可用于实盘，无需修改。

### 1.1 内部架构

| 组件 | 访问方式 | 何时可用 | 说明 |
|------|---------|---------|------|
| **配置** | `self.config` | `__init__` 后 | 策略配置对象 |
| **时钟** | `self.clock` / `self._clock` | 注册后 | UTC 时钟、定时器、时间警报 |
| **日志** | `self.log` / `self._log` | 注册后 | 结构化日志器 |
| **缓存** | `self.cache` | 注册后 | 中央数据/执行对象存储 |
| **投资组合** | `self.portfolio` | 注册后 | 账户与持仓信息查询 |
| **订单工厂** | `self.order_factory` | 注册后 | 创建各类订单 |
| **消息总线** | `self._msgbus` | 注册后 | 内部事件发布订阅 |

> `cache`、`portfolio`、`order_factory` 在 `__init__` 时为 `None`，只有注册到 `Trader` 后才初始化。

### 1.2 策略 ID 与订单 ID 标签

```
strategy_id = "{ClassName}-{order_id_tag}"
# 例如：EMACross-BTC、PmccStrategy-SPX
```

- 不同策略实例的 `order_id_tag` 必须唯一，否则注册时抛出 `RuntimeError`

---

## 2. 策略基本结构

```python
from nautilus_trader.trading.strategy import Strategy


class MyStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__()  # 必须调用父类构造函数
```

> ⚠️ 不要在 `__init__` 中使用 `self.clock` 或 `self.log`，此时它们尚未初始化。

---

## 3. 策略配置（StrategyConfig）

### 3.1 定义配置类

```python
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId


class MyStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId        # 交易品种
    bar_type: BarType                  # K线类型
    trade_size: Decimal                # 每笔交易数量
    fast_ema_period: int = 10
    slow_ema_period: int = 20
    order_id_tag: str                  # 订单ID标签
```

### 3.2 本仓库的典型配置实例

```python
# ── Binance BTC 合约 ──
config = MyStrategyConfig(
    instrument_id=InstrumentId.from_str("BTCUSDT-PERP.BINANCE"),
    bar_type=BarType.from_str("BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL"),
    trade_size=Decimal("0.001"),
    order_id_tag="BTC",
)

# ── IBKR 美股期权（PMCC 策略） ──
config = PmccConfig(
    instrument_id=InstrumentId.from_str("SPX.XCBO"),
    bar_type=BarType.from_str("SPX.XCBO-1-DAY-LAST-EXTERNAL"),
    trade_size=Decimal("1"),
    order_id_tag="PMCC_SPX",
)
```

### 3.3 StrategyConfig 完整参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `strategy_id` | `StrategyId \| None` | `None` | 自定义策略 ID |
| `order_id_tag` | `str \| None` | `None` | 订单 ID 标签，必须全局唯一 |
| `oms_type` | `str \| None` | `None` | `UNSPECIFIED`/`HEDGING`/`NETTING` |
| `external_order_claims` | `list \| None` | `None` | 声明外部订单归属的品种 ID |
| `manage_contingent_orders` | `bool` | `False` | 自动管理 OTO/OCO/OUO 条件订单 |
| `manage_gtd_expiry` | `bool` | `False` | 策略本地管理 GTD 过期 |
| `manage_stop` | `bool` | `False` | 停止时自动执行市场退出 |
| `market_exit_interval_ms` | `int` | `100` | 市场退出检查间隔 |
| `market_exit_max_attempts` | `int` | `100` | 市场退出最大检查次数 |
| `market_exit_time_in_force` | `TimeInForce` | `GTC` | 平仓市价单有效期 |
| `market_exit_reduce_only` | `bool` | `True` | 平仓市价单是否仅减仓 |
| `log_events` | `bool` | `True` | 记录事件日志 |
| `log_commands` | `bool` | `True` | 记录命令日志 |

**OMS 类型说明：**

| OMS 类型 | 说明 | 适用场景 |
|----------|------|---------|
| `UNSPECIFIED` | 使用交易所原生 OMS | 默认 |
| `HEDGING` | 每笔开仓分配独立持仓 ID | IBKR 对冲模式 |
| `NETTING` | 每个品种仅一个持仓 | Binance 合约 |

---

## 4. 生命周期处理器

```python
def on_start(self) -> None:    # 策略启动
def on_stop(self) -> None:     # 策略停止
def on_resume(self) -> None:   # 策略恢复
def on_reset(self) -> None:    # 策略重置
def on_dispose(self) -> None:  # 策略销毁
def on_save(self) -> dict[str, bytes]:     # 保存状态
def on_load(self, state: dict[str, bytes]) -> None:  # 加载状态
```

### 4.1 `on_start()` — 策略启动

```python
def on_start(self) -> None:
    # 1. 从缓存获取品种
    self.instrument = self.cache.instrument(self.config.instrument_id)
    if self.instrument is None:
        self.log.error(f"找不到品种 {self.config.instrument_id}")
        self.stop()
        return

    # 2. 注册指标
    self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
    self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)

    # 3. 请求历史数据，完成后订阅实时K线
    self.request_bars(
        self.config.bar_type,
        callback=lambda _: self.subscribe_bars(self.config.bar_type),
    )

    # 4. 订阅成交 Tick
    self.subscribe_trade_ticks(self.config.instrument_id)
```

> 💡 实盘中先 `request_bars()` 请求历史数据，在回调中再 `subscribe_bars()` 订阅实时K线，确保数据序列连续。

### 4.2 `on_stop()` — 策略停止

```python
def on_stop(self) -> None:
    self.cancel_all_orders(self.config.instrument_id)
    self.close_all_positions(self.config.instrument_id)
    self.unsubscribe_bars(self.config.bar_type)
    self.unsubscribe_trade_ticks(self.config.instrument_id)
```

### 4.3 `on_resume()` — 策略恢复

策略从 STOPPED 状态恢复运行时调用。如果策略在实盘中被停止后重新启动，需要在此恢复数据订阅：

```python
def on_resume(self) -> None:
    """策略恢复运行时重新订阅数据"""
    self.subscribe_bars(self.config.bar_type)
    self.subscribe_trade_ticks(self.config.instrument_id)
```

### 4.4 `on_reset()` — 策略重置

策略被重置时调用，通常在回测中多次运行之间。重置所有自定义状态和指标：

```python
def on_reset(self) -> None:
    """重置指标和自定义状态"""
    self.fast_ema.reset()
    self.slow_ema.reset()
    self.bar_count = 0
    self.instrument = None
```

### 4.5 `on_degrade()` — 策略降级

策略运行中出现问题时降级调用。可用于切换到安全模式（如只减仓不开新仓）：

```python
def on_degrade(self) -> None:
    """策略降级：切换到安全模式"""
    self.log.warning("策略降级，仅允许减仓操作")
    self.degraded = True
```

### 4.6 `on_fault()` — 策略故障

策略遇到严重故障时调用。应在此停止所有操作：

```python
def on_fault(self) -> None:
    """策略故障：停止所有交易"""
    self.log.error("策略故障，停止交易")
    self.cancel_all_orders(self.config.instrument_id)
```

### 4.7 `on_dispose()` — 策略销毁

策略被永久销毁前调用，释放资源：

```python
def on_dispose(self) -> None:
    """释放策略持有的资源"""
    # 关闭自定义线程、数据库连接等
    pass
```

### 4.8 `on_save()` / `on_load()` — 状态持久化

用于在策略重启时保存和恢复自定义状态。当 `TradingNode` 配置了 Redis/Postgres 缓存时，状态会自动持久化：

```python
def on_save(self) -> dict[str, bytes]:
    return {"counter": str(self.bar_count).encode("utf-8")}

def on_load(self, state: dict[str, bytes]) -> None:
    if "counter" in state:
        self.bar_count = int(state["counter"].decode("utf-8"))
```

### 4.9 生命周期状态转换

```
          on_start()
  INITIALIZED ──────→ RUNNING
                        │  ↑
                   stop │  │ on_resume
                        ↓  │
                      STOPPED
                        │
                   reset │
                        ↓
                      RESETTABLE
                        │
                   fault │  degrade
                        ↓  ↓
                     FAULTED  DEGRADED
```

---

## 5. 数据处理器

策略通过实现 `on_*` 方法来接收市场数据和自定义数据。只需实现你需要的处理器。

### 5.1 所有数据处理器一览

| 处理器 | 数据类型 | 典型用途 |
|--------|---------|---------|
| `on_bar(bar)` | K线 | 信号计算、指标更新 |
| `on_quote_tick(tick)` | 报价 Tick | 做市策略、盘口分析 |
| `on_trade_tick(tick)` | 成交 Tick | 成交量分析、订单流 |
| `on_order_book_deltas(deltas)` | 订单簿增量 | 高频做市、深度分析 |
| `on_order_book(order_book)` | 订单簿快照 | 完整盘口状态 |
| `on_instrument(instrument)` | 品种信息 | 品种更新（合约规格变化） |
| `on_instrument_status(data)` | 品种状态 | 交易时段、暂停/恢复 |
| `on_instrument_close(data)` | 品种收盘 | 收盘价处理 |
| `on_option_greeks(greeks)` | 期权希腊值 | 期权策略（IBKR） |
| `on_option_chain(chain)` | 期权链切片 | 期权链扫描（IBKR） |
| `on_historical_data(data)` | 历史数据响应 | 历史数据请求的回调 |
| `on_data(data)` | 自定义数据 | 接收任意自定义数据 |
| `on_signal(signal)` | 自定义信号 | 接收来自 Actor 的信号 |

### 5.2 数据订阅方法

在 `on_start()` 中订阅数据，对应的处理器才会被触发：

```python
def on_start(self) -> None:
    # ── K线 ──
    self.subscribe_bars(bar_type)

    # ── Tick 数据 ──
    self.subscribe_quote_ticks(instrument_id)
    self.subscribe_trade_ticks(instrument_id)

    # ── 订单簿 ──
    self.subscribe_order_book_deltas(instrument_id, depth=20)
    self.subscribe_order_book_at_interval(instrument_id, depth=20)

    # ── IBKR 期权链 ──
    self.subscribe_option_chain(instrument_id)

    # ── 品种状态 ──
    self.subscribe_instrument_status(instrument_id)
    self.subscribe_instrument_close(instrument_id)
```

### 5.3 请求历史数据

```python
def on_start(self) -> None:
    # 请求历史K线（可指定起止时间和回调）
    self.request_bars(
        bar_type,
        start=start_time,
        end=end_time,
        callback=self._on_historical_bars,  # 可选回调
    )

    # 请求历史报价
    self.request_quote_ticks(instrument_id, start=start_time)

    # 请求历史成交
    self.request_trade_ticks(instrument_id, start=start_time)

    # 请求品种信息
    self.request_instrument(instrument_id)
    self.request_instruments(venue)
```

### 5.4 取消订阅

在 `on_stop()` 中取消订阅，避免收到不必要的数据：

```python
def on_stop(self) -> None:
    self.unsubscribe_bars(bar_type)
    self.unsubscribe_quote_ticks(instrument_id)
    self.unsubscribe_trade_ticks(instrument_id)
    self.unsubscribe_order_book_deltas(instrument_id)
    self.unsubscribe_instrument_status(instrument_id)
    self.unsubscribe_instrument_close(instrument_id)
```

### 5.5 IBKR 期权链示例

PMCC 策略需要接收期权链数据来选择要卖出的 Call：

```python
def on_option_chain(self, chain: OptionChainSlice) -> None:
    """收到期权链更新时选择要卖出的合约"""
    for option in chain.options:
        if option.right == OptionRight.CALL:
            # 用 shared/selection.py 的 select_short_option 过滤
            ...
```

### 5.6 自定义数据与信号

`on_data` 接收自定义数据类型（如来自外部 API 的数据），`on_signal` 接收来自其他 Actor 的信号：

```python
def on_data(self, data: Data) -> None:
    """接收自定义数据"""
    if isinstance(data, MyCustomData):
        self.process_custom_data(data)

def on_signal(self, signal: Data) -> None:
    """接收来自 Actor 的信号"""
    if isinstance(signal, EntrySignal):
        self.handle_entry_signal(signal)
```

---

## 6. 订单管理

### 6.1 订单工厂方法一览

`self.order_factory` 提供以下快捷方法创建各类订单：

| 方法 | 订单类型 | 说明 |
|------|---------|------|
| `order_factory.market(...)` | `MarketOrder` | 市价单 |
| `order_factory.limit(...)` | `LimitOrder` | 限价单 |
| `order_factory.stop_market(...)` | `StopMarketOrder` | 止损市价单 |
| `order_factory.stop_limit(...)` | `StopLimitOrder` | 止损限价单 |
| `order_factory.market_to_limit(...)` | `MarketToLimitOrder` | 市价转限价单 |
| `order_factory.limit_if_touched(...)` | `LimitIfTouchedOrder` | 触及限价单 |
| `order_factory.trailing_stop_market(...)` | `TrailingStopMarketOrder` | 追踪止损单 |
| `order_factory.trailing_stop_limit(...)` | `TrailingStopLimitOrder` | 追踪止损限价单 |
| `order_factory.bracket(...)` | `OrderList` | 括号订单（入场+止盈+止损） |

### 6.2 市价单（Market Order）

```python
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.orders import MarketOrder


order: MarketOrder = self.order_factory.market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self.instrument.make_qty(self.config.trade_size),
    time_in_force=TimeInForce.GTC,
)
self.submit_order(order)
```

**TimeInForce 可选值：**

| 值 | 说明 | 适用场景 |
|----|------|---------|
| `GTC` | Good Till Cancelled | 默认，一直有效直到取消 |
| `IOC` | Immediate Or Cancel | Binance 合约常用，立即成交否则取消 |
| `FOK` | Fill Or Kill | 要么全部成交，要么全部取消 |
| `GTD` | Good Till Date | 到指定时间过期（需配合 `expire_time`） |
| `DAY` | 当日有效 | IBKR 股票常用 |

### 6.3 限价单（Limit Order）

```python
from nautilus_trader.model.enums import TriggerType
from nautilus_trader.model.orders import LimitOrder


order: LimitOrder = self.order_factory.limit(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self.instrument.make_qty(self.config.trade_size),
    price=self.instrument.make_price(100000.00),
    # 可选参数
    time_in_force=TimeInForce.GTC,
    expire_time=pd.Timestamp("2025-12-31", tz="UTC"),  # GTD 时需指定
    emulation_trigger=TriggerType.LAST_PRICE,  # 本地模拟触发
    post_only=True,  # 只做 Maker（Binance 支持）
)
self.submit_order(order)
```

### 6.4 止损市价单（Stop Market Order）

```python
order = self.order_factory.stop_market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.SELL,
    quantity=self.instrument.make_qty(self.config.trade_size),
    trigger_price=self.instrument.make_price(95000.00),
    # 可选参数
    emulation_trigger=TriggerType.LAST_PRICE,  # 用最新成交价触发
)
self.submit_order(order)
```

### 6.5 追踪止损单（Trailing Stop Order）

```python
order = self.order_factory.trailing_stop_market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.SELL,
    quantity=self.instrument.make_qty(self.config.trade_size),
    trigger_price=self.instrument.make_price(95000.00),  # 初始触发价
    trailing_offset=self.instrument.make_price(500.00),   # 追踪偏移
    trailing_offset_type=TrailingOffsetType.PRICE,       # 价格偏移
)
self.submit_order(order)
```

### 6.6 括号订单（Bracket Order）— Binance 合约常用

括号订单同时设置入场、止盈和止损，返回一个 `OrderList`：

```python
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Price, Quantity


bracket = self.order_factory.bracket(
    instrument_id=InstrumentId.from_str("BTCUSDT-PERP.BINANCE"),
    order_side=OrderSide.BUY,
    quantity=Quantity.from_int(1),
    # 入场单（默认 LIMIT 单）
    entry_price=Price.from_str("100000.00"),           # 可选，省略则为市价入场
    # 止盈
    tp_price=Price.from_str("110000.00"),               # 止盈价（默认 LIMIT 单）
    tp_trigger_price=Price.from_str("109000.00"),        # 可选：止盈触发价
    # 止损
    sl_trigger_price=Price.from_str("95000.00"),         # 止损触发价（默认 STOP_MARKET）
    sl_price=Price.from_str("94900.00"),                 # 可选：止损限价（STOP_LIMIT 时需要）
    # 其他
    emulation_trigger=TriggerType.LAST_PRICE,            # 可选：本地模拟触发
)
self.submit_order_list(bracket)
```

### 6.7 IBKR 期权多腿订单

本仓库的 `shared/legs.py` 提供了 `LegGroup` 多腿状态机，用于管理 PMCC 等策略的多腿订单：

```python
# PMCC 策略：买入深 ITM LEAPS + 卖出近 OTM Call
# 每腿独立提交，LegGroup 跟踪填充状态
self.submit_order(long_leg_order)
self.submit_order(short_leg_order)
```

### 6.8 提交订单

`submit_order` 完整签名：

```python
def submit_order(
    self,
    order: Order,
    position_id: PositionId = None,     # 指定持仓 ID
    client_id: ClientId = None,          # 指定执行客户端（多交易所时）
    params: dict[str, object] = None,    # 附加参数
) -> None:
```

`submit_order_list` 完整签名（用于括号订单等）：

```python
def submit_order_list(
    self,
    order_list: OrderList,
    position_id: PositionId = None,
    client_id: ClientId = None,
    params: dict[str, object] = None,
) -> None:
```

**订单路由逻辑：**

```
订单有 emulation_trigger?  →  OrderEmulator
├─ 否则，有 exec_algorithm_id?  →  ExecAlgorithm
└─ 否则  →  RiskEngine
```

> ⚠️ 市场退出期间（`is_exiting() == True`），非 reduce-only 的订单会被自动拒绝。

### 6.9 取消订单

```python
# 取消单个订单
self.cancel_order(order)

# 批量取消（注意：不支持模拟订单，所有订单必须属于同一品种）
self.cancel_orders([order1, order2])

# 取消某品种所有订单（可按方向过滤）
self.cancel_all_orders(instrument_id)
self.cancel_all_orders(instrument_id, order_side=OrderSide.BUY)  # 仅买单

# 取消所有品种的所有订单
self.cancel_all_orders()
```

### 6.10 修改订单

```python
from nautilus_trader.model.objects import Quantity, Price

# 修改数量
self.modify_order(order, quantity=Quantity.from_int(5))

# 修改价格（仅限 LIMIT 类订单）
self.modify_order(order, price=self.instrument.make_price(5100.00))

# 修改触发价（仅限 STOP 类订单）
self.modify_order(order, trigger_price=self.instrument.make_price(4800.00))

# 同时修改多个参数
self.modify_order(order, quantity=new_qty, price=new_price, trigger_price=new_trigger)
```

> ⚠️ 至少要有一个值与原订单不同，否则命令无效。已交给执行算法管理的订单不能直接修改，只能取消。

### 6.11 订单事件处理器（完整列表）

订单状态变化按 **特定 → 通用** 顺序调用：`on_order_xxx → on_order_event → on_event`

```python
from nautilus_trader.model.events import (
    OrderInitialized,       # 订单初始化（submit 前触发）
    OrderDenied,            # 订单被本地风控拒绝
    OrderEmulated,          # 订单进入模拟器
    OrderReleased,          # 订单从模拟器释放
    OrderSubmitted,         # 订单已提交到交易所
    OrderAccepted,          # 订单已被交易所接受
    OrderRejected,          # 订单被交易所拒绝
    OrderPendingUpdate,     # 订单修改已提交（等待确认）
    OrderPendingCancel,     # 订单取消已提交（等待确认）
    OrderModifyRejected,    # 订单修改被拒绝
    OrderCancelRejected,    # 订单取消被拒绝
    OrderUpdated,           # 订单已更新
    OrderTriggered,         # 止损/止盈订单被触发
    OrderFilled,            # 订单已成交
    OrderCanceled,          # 订单已取消
    OrderExpired,           # 订单已过期
    OrderEvent,             # 所有订单事件的基类
)


def on_order_initialized(self, event: OrderInitialized) -> None: ...
def on_order_denied(self, event: OrderDenied) -> None: ...
def on_order_emulated(self, event: OrderEmulated) -> None: ...
def on_order_released(self, event: OrderReleased) -> None: ...
def on_order_submitted(self, event: OrderSubmitted) -> None: ...
def on_order_accepted(self, event: OrderAccepted) -> None: ...
def on_order_rejected(self, event: OrderRejected) -> None: ...
def on_order_pending_update(self, event: OrderPendingUpdate) -> None: ...
def on_order_pending_cancel(self, event: OrderPendingCancel) -> None: ...
def on_order_modify_rejected(self, event: OrderModifyRejected) -> None: ...
def on_order_cancel_rejected(self, event: OrderCancelRejected) -> None: ...
def on_order_updated(self, event: OrderUpdated) -> None: ...
def on_order_triggered(self, event: OrderTriggered) -> None: ...
def on_order_filled(self, event: OrderFilled) -> None: ...
def on_order_canceled(self, event: OrderCanceled) -> None: ...
def on_order_expired(self, event: OrderExpired) -> None: ...
def on_order_event(self, event: OrderEvent) -> None: ...       # 所有订单事件
```

**常用处理示例：**

```python
def on_order_filled(self, event: OrderFilled) -> None:
    """订单成交时更新状态"""
    self.log.info(f"订单成交: {event.client_order_id} "
                  f"方向={event.order_side} "
                  f"价格={event.last_px} "
                  f"数量={event.last_qty}")

def on_order_rejected(self, event: OrderRejected) -> None:
    """订单被交易所拒绝"""
    self.log.error(f"订单被拒绝: {event.client_order_id} 原因={event.reason}")

def on_order_denied(self, event: OrderDenied) -> None:
    """订单被本地风控拒绝"""
    self.log.error(f"订单被风控拒绝: {event.client_order_id} 原因={event.reason}")
```

### 6.12 使用执行算法

```python
from nautilus_trader.model.identifiers import ExecAlgorithmId


order = self.order_factory.market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self.instrument.make_qty(self.config.trade_size),
    time_in_force=TimeInForce.FOK,
    exec_algorithm_id=ExecAlgorithmId("TWAP"),
    exec_algorithm_params={"horizon_secs": 20, "interval_secs": 2.5},
)
self.submit_order(order)
```

### 6.13 GTD 订单过期管理

设置 `manage_gtd_expiry=True` 后，策略会自动管理 GTD 订单的过期：

```python
config = MyStrategyConfig(
    manage_gtd_expiry=True,  # 策略本地管理 GTD 过期
    ...
)

# 手动取消 GTD 过期定时器
self.cancel_gtd_expiry(order)
```

### 6.14 查询账户和订单

```python
from nautilus_trader.model.identifiers import AccountId


# 查询账户状态（触发 AccountState 事件）
self.query_account(AccountId("U1234567"))

# 查询订单状态（触发 OrderStatusReport）
self.query_order(order)
```

---

## 7. 持仓与投资组合

### 7.1 查询持仓方向

```python
# 是否无持仓
self.portfolio.is_flat(instrument_id)

# 是否净多头/净空头
self.portfolio.is_net_long(instrument_id)
self.portfolio.is_net_short(instrument_id)

# 是否完全无持仓（所有品种）
self.portfolio.is_completely_flat()
```

### 7.2 查询持仓详情

```python
# 净持仓量
net_position = self.portfolio.net_position(instrument_id)

# 未实现盈亏
unrealized_pnl = self.portfolio.unrealized_pnl(instrument_id)

# 已实现盈亏
realized_pnl = self.portfolio.realized_pnl(instrument_id)

# 净敞口
net_exposure = self.portfolio.net_exposure(instrument_id)
```

### 7.3 查询账户信息

```python
from nautilus_trader.model import Venue, Currency

# 获取账户对象
account = self.portfolio.account(Venue("BINANCE"))

# 锁定余额
balances_locked = self.portfolio.balances_locked(Venue("BINANCE"))

# 初始保证金
margins_init = self.portfolio.margins_init(Venue("BINANCE"))

# 维持保证金
margins_maint = self.portfolio.margins_maint(Venue("BINANCE"))

# 未实现盈亏（按交易所）
unrealized_pnls = self.portfolio.unrealized_pnls(Venue("BINANCE"))

# 已实现盈亏（按交易所）
realized_pnls = self.portfolio.realized_pnls(Venue("BINANCE"))

# 净敞口（按交易所）
net_exposures = self.portfolio.net_exposures(Venue("BINANCE"))
```

### 7.4 平仓

```python
# 平掉特定持仓（完整签名）
self.close_position(
    position,
    client_id=None,                # 指定执行客户端
    tags=None,                     # 平仓订单标签
    time_in_force=TimeInForce.GTC, # 平仓订单有效期
    reduce_only=True,              # 是否仅减仓
    quote_quantity=False,          # 数量是否以报价货币计
    params=None,                   # 附加参数
)

# 平掉某品种所有持仓（完整签名）
self.close_all_positions(
    instrument_id,
    position_side=PositionSide.NO_POSITION_SIDE,  # 按方向过滤
    client_id=None,
    tags=None,
    time_in_force=TimeInForce.GTC,
    reduce_only=True,
    quote_quantity=False,
    params=None,
)
```

**IBKR 期权行权跟踪：**

```python
# 在 IBKR ExecClientConfig 中启用
exec_config = InteractiveBrokersExecClientConfig(
    track_option_exercise_from_position_update=True,  # 跟踪期权行权
    ...
)
```

### 7.5 持仓事件

```
on_position_opened → on_position_changed → on_position_event → on_event
```

```python
def on_position_opened(self, event: PositionOpened) -> None:
    """新持仓打开"""
    self.log.info(f"开仓: {event.instrument_id} 方向={event.entry.direction}")

def on_position_changed(self, event: PositionChanged) -> None:
    """持仓变化（加仓/减仓/盈亏变化）"""
    self.log.info(f"持仓变化: {event.instrument_id} 数量={event.quantity}")

def on_position_closed(self, event: PositionClosed) -> None:
    """持仓平仓"""
    self.log.info(f"平仓: {event.instrument_id} 盈亏={event.realized_pnl}")

def on_position_event(self, event: PositionEvent) -> None:
    """所有持仓事件"""
    pass
```

---

## 8. 指标与缓存

### 8.1 内置指标

NautilusTrader 内置了丰富的技术指标：

| 指标 | 类名 | 说明 |
|------|------|------|
| EMA | `ExponentialMovingAverage` | 指数移动平均 |
| SMA | `SimpleMovingAverage` | 简单移动平均 |
| RSI | `RelativeStrengthIndex` | 相对强弱指标 |
| ATR | `AverageTrueRange` | 平均真实波幅 |
| Bollinger Bands | `BollingerBands` | 布林带 |
| MACD | `MovingAverageConvergenceDivergence` | MACD |
| VWAP | `VolumeWeightedAveragePrice` | 成交量加权平均价 |
| ADX | `AverageDirectionalIndex` | 平均趋向指标 |

### 8.2 创建和注册指标

```python
from nautilus_trader.indicators import ExponentialMovingAverage, RelativeStrengthIndex


class MyStrategy(Strategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)
        # 创建指标
        self.fast_ema = ExponentialMovingAverage(config.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_ema_period)
        self.rsi = RelativeStrengthIndex(14)

    def on_start(self) -> None:
        # 注册指标到K线（随K线自动更新）
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)

        # 也可以注册到 Tick 数据
        self.register_indicator_for_quotes(self.config.instrument_id, self.rsi)
        self.register_indicator_for_trades(self.config.instrument_id, self.rsi)

    def on_bar(self, bar: Bar) -> None:
        # 检查是否预热完毕
        if not self.indicators_initialized():
            return  # 等待预热

        # 使用指标值
        fast = self.fast_ema.value
        slow = self.slow_ema.value
        rsi = self.rsi.value
```

### 8.3 访问缓存

缓存存储了交易系统的数据和执行对象：

```python
# ── 品种 ──
instrument = self.cache.instrument(instrument_id)
instruments = self.cache.instruments(venue=Venue("BINANCE"))

# ── 市场数据 ──
last_quote = self.cache.quote_tick(instrument_id)
last_trade = self.cache.trade_tick(instrument_id)
last_bar = self.cache.bar(bar_type)
bar_count = self.cache.bar_count(bar_type)

# ── 订单 ──
order = self.cache.order(client_order_id)
open_orders = self.cache.orders_open(instrument_id=instrument_id)
orders = self.cache.orders(instrument_id=instrument_id, strategy_id=self.id)

# ── 持仓 ──
position = self.cache.position(position_id)
open_positions = self.cache.positions_open(instrument_id=instrument_id)
positions = self.cache.positions(instrument_id=instrument_id)

# ── 账户 ──
account = self.cache.account(account_id)
accounts = self.cache.accounts()
```

---

## 9. 时钟与定时器

### 9.1 获取当前时间

```python
import pandas as pd

# UTC 时间（带时区信息的 pd.Timestamp）
now: pd.Timestamp = self.clock.utc_now()

# UNIX 纳秒时间戳
unix_nanos: int = self.clock.timestamp_ns()
```

### 9.2 时间警报（一次性）

在指定时间触发 `TimeEvent`，可在 `on_event` 中处理：

```python
def on_start(self) -> None:
    # 设置 1 分钟后的时间警报
    self.clock.set_time_alert(
        name="ClosePositionsAlert",
        alert_time=self.clock.utc_now() + pd.Timedelta(minutes=1),
    )

def on_event(self, event: Event) -> None:
    if isinstance(event, TimeEvent) and event.name == "ClosePositionsAlert":
        self.log.info("时间到，平仓！")
        self.close_all_positions(self.config.instrument_id)
```

### 9.3 定时器（周期性）

```python
def on_start(self) -> None:
    # 每 5 分钟触发一次
    self.clock.set_timer(
        name="RebalanceTimer",
        interval=pd.Timedelta(minutes=5),
    )
```

### 9.4 取消定时器

```python
# 取消指定定时器
self.clock.cancel_timer(name="RebalanceTimer")

# 查看所有活动定时器
timer_names = self.clock.timer_names
```

---

## 10. 市场退出（Market Exit）

### 10.1 基本用法

```python
# 执行市场退出：取消所有订单 + 平掉所有持仓
self.market_exit()

# 退出期间跳过下单
def on_bar(self, bar: Bar) -> None:
    if self.is_exiting():
        return
    # ... 正常逻辑
```

### 10.2 自定义钩子

```python
def on_market_exit(self) -> None:
    """退出过程开始时调用"""
    self.log.info("开始市场退出...")

def post_market_exit(self) -> None:
    """退出过程完成后调用"""
    self.log.info("市场退出完成，所有持仓已平")
```

### 10.3 市场退出流程

1. 取消策略的所有挂单和在途订单
2. 用市价单平掉所有持仓
3. 定期检查（按 `market_exit_interval_ms` 间隔）直到所有订单完成且持仓平仓
4. 平仓完成后调用 `post_market_exit()`

### 10.4 自动退出配置

```python
config = StrategyConfig(
    manage_stop=True,               # 停止时自动执行市场退出
    market_exit_interval_ms=100,    # 检查间隔
    market_exit_max_attempts=100,   # 最大检查次数
    market_exit_reduce_only=True,   # 平仓仅减仓
    market_exit_time_in_force=TimeInForce.GTC,  # 平仓单有效期
)
```

---

## 11. 通用事件处理

`on_event` 是最通用的事件处理器，所有事件最终都会到达这里。可用它处理定时器事件和统一的事件路由：

```python
from nautilus_trader.core.message import Event
from nautilus_trader.common.component import TimeEvent


def on_event(self, event: Event) -> None:
    """接收所有事件"""
    if isinstance(event, TimeEvent):
        self._handle_timer(event)
    # 其他事件类型已经被对应的 on_order_xxx / on_position_xxx 等处理过

def _handle_timer(self, event: TimeEvent) -> None:
    """处理定时器事件"""
    if event.name == "RebalanceTimer":
        self._rebalance()
    elif event.name == "ClosePositionsAlert":
        self.close_all_positions(self.config.instrument_id)
```

> 💡 事件调用顺序始终是 **特定 → 通用**：`on_order_filled → on_order_event → on_event`。如果你只需要处理特定事件，实现具体的处理器即可。

---

## 11. 完整示例

### 11.1 EMA 交叉策略（Binance BTC）

```python
from decimal import Decimal

import pandas as pd

from nautilus_trader.common.enums import LogColor
from nautilus_trader.config import PositiveInt, StrategyConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.trading.strategy import Strategy


class EMACrossConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    fast_ema_period: PositiveInt = 10
    slow_ema_period: PositiveInt = 20
    close_positions_on_stop: bool = True


class EMACross(Strategy):
    def __init__(self, config: EMACrossConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self.fast_ema = ExponentialMovingAverage(config.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_ema_period)

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"找不到品种: {self.config.instrument_id}")
            self.stop()
            return

        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)

        self.request_bars(
            self.config.bar_type,
            start=self._clock.utc_now() - pd.Timedelta(days=1),
            callback=lambda _: self.subscribe_bars(self.config.bar_type),
        )
        self.subscribe_trade_ticks(self.config.instrument_id)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return
        if bar.is_single_price():
            return

        if self.fast_ema.value >= self.slow_ema.value:
            if self.portfolio.is_flat(self.config.instrument_id):
                self.buy()
            elif self.portfolio.is_net_short(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.buy()
        elif self.fast_ema.value < self.slow_ema.value:
            if self.portfolio.is_flat(self.config.instrument_id):
                self.sell()
            elif self.portfolio.is_net_long(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.sell()

    def buy(self) -> None:
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def sell(self) -> None:
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        if self.config.close_positions_on_stop:
            self.close_all_positions(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)
        self.unsubscribe_trade_ticks(self.config.instrument_id)

    def on_reset(self) -> None:
        self.fast_ema.reset()
        self.slow_ema.reset()

    def on_save(self) -> dict[str, bytes]:
        return {}

    def on_load(self, state: dict[str, bytes]) -> None:
        pass
```

### 11.2 本仓库策略参考

本仓库 `packages/trade-system-strategies/` 已实现以下策略：

| 策略 | 位置 | 适用场景 | 状态 |
|------|------|---------|------|
| **RSI 双触** | `rsi/` | Binance BTC 合约均值回归 | ✅ 完整实现 |
| **PMCC** | `pmcc/` | IBKR 美股期权（穷人的备兑） | 🏗️ 脚手架 |
| **Backspread** | `backspread/` | IBKR 期权看涨后价差 | 🏗️ 脚手架 |

策略结构统一为三文件分离：`config.py`（配置）· `signals.py`（纯函数信号）· `strategy.py`（NautilusTrader 胶水代码）。

---

## 12. 最佳实践

1. **不要在 `__init__` 中使用 `self.clock`/`self.log`** — 注册后才可用
2. **始终检查 `indicators_initialized()`** — 未预热的指标返回无效值
3. **先 `request_bars()` 再 `subscribe_bars()`** — 确保数据序列连续
4. **品种检查** — `on_start()` 中获取品种后检查 `None`
5. **配置与状态分离** — 配置走 `self.config`，状态走 `self.xxx`
6. **不要阻塞事件循环** — 长时间任务卸载到独立线程/进程
7. **启用 `manage_stop=True`** — 确保异常停止时自动平仓
8. **事件处理顺序** — 具体 → 通用：`on_order_filled → on_order_event → on_event`
