# 实盘部署指南

将策略从回测部署到实盘交易，涵盖 TradingNode 配置、Binance/IBKR 适配器、容器化和 Kubernetes 部署。

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────┐
│                    TradingNode                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Strategy │  │  Actor   │  │  ExecAlgorithm   │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│  ┌────┴──────────────┴─────────────────┴─────────┐  │
│  │              MessageBus                        │  │
│  └────┬──────────────┬─────────────────┬────────┘  │
│  ┌────┴────┐  ┌──────┴──────┐  ┌──────┴──────┐    │
│  │DataEngine│  │ RiskEngine  │  │ ExecEngine  │    │
│  └────┬────┘  └──────┬──────┘  └──────┬──────┘    │
│  ┌────┴────┐         │           ┌─────┴──────┐    │
│  │DataClient│         │           │ ExecClient │    │
│  └────┬────┘         │           └─────┬──────┘    │
└───────┼──────────────┼─────────────────┼────────────┘
        │              │                 │
   ┌────┴──────────────┴─────────────────┴──────┐
   │   Binance API (BTC 合约)  ·  IBKR Gateway  │
   └────────────────────────────────────────────┘
```

**关键约束：** 每个进程只能运行一个 `TradingNode`。策略回调不能阻塞事件循环。

---

## 2. 从回测到实盘：零代码修改

同一份策略代码，回测用 `BacktestEngine`，实盘用 `TradingNode`，策略本身无需任何改动。

---

## 3. TradingNode 配置

```python
from nautilus_trader.config import TradingNodeConfig

config = TradingNodeConfig(
    trader_id="LIVE-001",
    timeout_connection=60.0,
    timeout_reconciliation=30.0,
    timeout_portfolio=10.0,
    timeout_disconnection=10.0,
    timeout_post_stop=10.0,
    data_clients={...},   # 数据客户端
    exec_clients={...},   # 执行客户端
)
```

---

## 4. 交易所适配器配置

### 4.1 Binance（比特币合约）

```python
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.futures.enums import BinanceFuturesMarginType
from nautilus_trader.adapters.binance.common.symbol import BinanceSymbol
from nautilus_trader.config import InstrumentProviderConfig, PositiveInt


data_config = BinanceDataClientConfig(
    api_key=None,                           # 从 BINANCE_API_KEY 环境变量读取
    api_secret=None,                        # 从 BINANCE_API_SECRET 环境变量读取
    account_type=BinanceAccountType.USDT_FUTURES,
    environment=BinanceEnvironment.LIVE,    # LIVE / TESTNET / DEMO
    instrument_provider=InstrumentProviderConfig(load_all=True),
)

exec_config = BinanceExecClientConfig(
    api_key=None,
    api_secret=None,
    account_type=BinanceAccountType.USDT_FUTURES,
    environment=BinanceEnvironment.LIVE,
    use_gtd=True,
    use_reduce_only=True,
    use_position_ids=True,
    recv_window_ms=5_000,
    futures_leverages={
        BinanceSymbol("BTCUSDT"): PositiveInt(10),   # 10x 杠杆
    },
    futures_margin_types={
        BinanceSymbol("BTCUSDT"): BinanceFuturesMarginType.CROSS,  # 全仓模式
    },
    instrument_provider=InstrumentProviderConfig(load_all=True),
)
```

### 4.2 Binance 测试网（Testnet）— 模拟账户

币安提供专门的合约测试网，用于无风险验证策略。**强烈建议在实盘之前，先用测试网完整验证下单、平仓、对账流程。**

```python
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.futures.enums import BinanceFuturesMarginType
from nautilus_trader.adapters.binance.common.symbol import BinanceSymbol
from nautilus_trader.config import InstrumentProviderConfig, PositiveInt


testnet_data_config = BinanceDataClientConfig(
    api_key=None,           # 从 BINANCE_TESTNET_API_KEY 环境变量读取（注意变量名！）
    api_secret=None,        # 从 BINANCE_TESTNET_API_SECRET 环境变量读取
    account_type=BinanceAccountType.USDT_FUTURES,
    environment=BinanceEnvironment.TESTNET,  # ← 关键：切换到测试网
    instrument_provider=InstrumentProviderConfig(load_all=True),
)

testnet_exec_config = BinanceExecClientConfig(
    api_key=None,
    api_secret=None,
    account_type=BinanceAccountType.USDT_FUTURES,
    environment=BinanceEnvironment.TESTNET,  # ← 关键：切换到测试网
    use_gtd=True,
    use_reduce_only=True,
    use_position_ids=True,
    recv_window_ms=5_000,
    futures_leverages={
        BinanceSymbol("BTCUSDT"): PositiveInt(10),
    },
    futures_margin_types={
        BinanceSymbol("BTCUSDT"): BinanceFuturesMarginType.CROSS,
    },
    instrument_provider=InstrumentProviderConfig(load_all=True),
)
```

#### 测试网 vs 实盘差异

| 项目 | 实盘 (LIVE) | 测试网 (TESTNET) | Demo (DEMO) |
|------|------------|-----------------|-------------|
| `environment` | `BinanceEnvironment.LIVE` | `BinanceEnvironment.TESTNET` | `BinanceEnvironment.DEMO` |
| API 基础 URL | `api.binance.com` | `testnet.binancefuture.com` | 自动 |
| WebSocket URL | 实盘地址 | 测试网地址 | 自动 |
| API Key 变量 | `BINANCE_API_KEY` | `BINANCE_TESTNET_API_KEY` | `BINANCE_API_KEY` |
| API Secret 变量 | `BINANCE_API_SECRET` | `BINANCE_TESTNET_API_SECRET` | `BINANCE_API_SECRET` |
| 获取测试网密钥 | — | 币安合约测试网官网¹ | — |
| 交易资金 | 真实资金 | 虚拟 USDT（免费领取） | 模拟 |
| 订单行为 | 真实撮合 | 模拟撮合 | 模拟撮合 |
| 对账 | 真实 | 模拟 | 模拟 |

¹ 币安合约测试网：https://testnet.binancefuture.com

#### 测试网环境变量

```bash
# ⚠️ 测试网密钥变量名与实盘不同！
# 当 environment=TESTNET 时，适配器自动从以下变量读取：
export BINANCE_TESTNET_API_KEY="your-testnet-key"
export BINANCE_TESTNET_API_SECRET="your-testnet-secret"
```

> 💡 测试网 API 密钥需要在币安合约测试网官网登录后获取，与实盘密钥完全独立。

#### 测试网获取虚拟资金

1. 访问 https://testnet.binancefuture.com
2. 用 GitHub 账号登录
3. 点击右上角钱包 → "Get Test Funds" 获取虚拟 USDT
4. 在 API Management 创建 API Key

### 4.3 IBKR（Interactive Brokers）

IBKR 需要运行 IB Gateway 或 TWS，支持 Docker 化部署：

```python
from nautilus_trader.adapters.interactive_brokers.config import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
    DockerizedIBGatewayConfig,
)
from nautilus_trader.adapters.interactive_brokers.common import IBContract


# Docker 化 IB Gateway（K8s 推荐方案）
docker_gateway = DockerizedIBGatewayConfig(
    username=None,           # 从 TWS_USERNAME 环境变量读取
    password=None,           # 从 TWS_PASSWORD 环境变量读取
    trading_mode="live",     # "paper" 或 "live"
    read_only_api=False,     # False 才能执行订单
    timeout=300,
    container_image="ghcr.io/gnzsnz/ib-gateway:stable",
    vnc_port=5900,           # 可选：VNC 远程桌面
)

data_config = InteractiveBrokersDataClientConfig(
    ibg_host="127.0.0.1",
    ibg_port=4001,           # IBG live: 4001, paper: 4002
    ibg_client_id=1,
    use_regular_trading_hours=True,
    dockerized_gateway=docker_gateway,
    connection_timeout=300,
    request_timeout_secs=60,
    instrument_provider=InteractiveBrokersInstrumentProviderConfig(
        load_contracts=frozenset({
            IBContract(symbol="SPX", sec_type="IND", exchange="CBOE"),
            IBContract(symbol="AAPL", sec_type="STK", exchange="SMART"),
        }),
        build_options_chain=True,    # 加载期权链
        min_expiry_days=1,
        max_expiry_days=90,
    ),
)

exec_config = InteractiveBrokersExecClientConfig(
    ibg_host="127.0.0.1",
    ibg_port=4001,
    ibg_client_id=1,
    account_id=None,          # 从 TWS_ACCOUNT 环境变量读取
    dockerized_gateway=docker_gateway,
    connection_timeout=300,
    fetch_all_open_orders=False,
    track_option_exercise_from_position_update=True,
)
```

### 4.4 API 密钥管理

```bash
# ── Binance 实盘 ──
export BINANCE_API_KEY="your-key"
export BINANCE_API_SECRET="your-secret"

# ── Binance 测试网（变量名不同！） ──
export BINANCE_TESTNET_API_KEY="testnet-key"
export BINANCE_TESTNET_API_SECRET="testnet-secret"

# ── IBKR ──
export TWS_USERNAME="your-ibkr-username"
export TWS_PASSWORD="your-ibkr-password"
export TWS_ACCOUNT="U1234567"
```

> ⚠️ 不要在代码中硬编码密钥！使用环境变量或 K8s Secret。

> 💡 Binance 适配器的密钥读取规则：当 `api_key=None` 时，适配器根据 `environment` 自动选择对应的环境变量——`LIVE` 读 `BINANCE_API_KEY`，`TESTNET` 读 `BINANCE_TESTNET_API_KEY`。

---

## 5. 完整实盘启动脚本

### 5.1 Binance BTC 合约

```python
# live_binance.py
import os
from decimal import Decimal

from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory, BinanceLiveExecClientFactory
from nautilus_trader.config import InstrumentProviderConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from strategies.ema_cross import EMACross, EMACrossConfig


def main():
    trader_id = os.environ.get("TRADER_ID", "LIVE-001")
    instrument_id = os.environ.get("INSTRUMENT_ID", "BTCUSDT-PERP.BINANCE")
    bar_type = os.environ.get("BAR_TYPE", "BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL")
    trade_size = Decimal(os.environ.get("TRADE_SIZE", "0.001"))

    # ── 通过 BINANCE_ENV 切换实盘/测试网 ──
    # "LIVE" → 实盘（读取 BINANCE_API_KEY）
    # "TESTNET" → 测试网（读取 BINANCE_TESTNET_API_KEY）
    env_str = os.environ.get("BINANCE_ENV", "LIVE").upper()
    environment = BinanceEnvironment[env_str]

    data_config = BinanceDataClientConfig(
        api_key=None,                   # 自动根据 environment 读取对应变量
        api_secret=None,
        account_type=BinanceAccountType.USDT_FUTURES,
        environment=environment,
        instrument_provider=InstrumentProviderConfig(load_all=True),
    )

    exec_config = BinanceExecClientConfig(
        api_key=None,
        api_secret=None,
        account_type=BinanceAccountType.USDT_FUTURES,
        environment=environment,
        instrument_provider=InstrumentProviderConfig(load_all=True),
    )

    strategy_config = EMACrossConfig(
        instrument_id=InstrumentId.from_str(instrument_id),
        bar_type=BarType.from_str(bar_type),
        trade_size=trade_size,
        order_id_tag="BTC",
        manage_stop=True,
    )

    node_config = TradingNodeConfig(
        trader_id=trader_id,
        data_clients={"BINANCE": data_config},
        exec_clients={"BINANCE": exec_config},
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()
    node.trader.add_strategy(EMACross(config=strategy_config))

    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop()
        finally:
            node.dispose()


if __name__ == "__main__":
    main()
```

### 5.2 IBKR 期权

```python
# live_ibkr.py
import os

from nautilus_trader.adapters.interactive_brokers.config import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    DockerizedIBGatewayConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from strategies.pmcc import PmccStrategy, PmccConfig


def main():
    docker_gateway = DockerizedIBGatewayConfig(
        username=None,
        password=None,
        trading_mode=os.environ.get("IBKR_MODE", "paper"),
        read_only_api=False,
    )

    data_config = InteractiveBrokersDataClientConfig(
        ibg_host=os.environ.get("IBG_HOST", "127.0.0.1"),
        ibg_port=int(os.environ.get("IBG_PORT", "4002")),
        dockerized_gateway=docker_gateway,
    )

    exec_config = InteractiveBrokersExecClientConfig(
        ibg_host=os.environ.get("IBG_HOST", "127.0.0.1"),
        ibg_port=int(os.environ.get("IBG_PORT", "4002")),
        account_id=None,
        dockerized_gateway=docker_gateway,
    )

    strategy_config = PmccConfig(
        order_id_tag="PMCC",
        manage_stop=True,
        oms_type="HEDGING",
    )

    node_config = TradingNodeConfig(
        trader_id="IBKR-001",
        data_clients={"IBKR": data_config},
        exec_clients={"IBKR": exec_config},
    )

    node = TradingNode(config=node_config)
    node.add_data_client_factory("IBKR", InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory("IBKR", InteractiveBrokersLiveExecClientFactory)
    node.build()
    node.trader.add_strategy(PmccStrategy(config=strategy_config))

    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop()
        finally:
            node.dispose()


if __name__ == "__main__":
    main()
```

---

## 6. 执行引擎配置

```python
from nautilus_trader.live.config import LiveExecEngineConfig

exec_engine_config = LiveExecEngineConfig(
    reconciliation=True,
    reconciliation_startup_delay_secs=10.0,
    inflight_check_interval_ms=2_000,
    inflight_check_threshold_ms=5_000,
    open_check_interval_secs=10.0,
    position_check_interval_secs=60.0,
    purge_closed_orders_interval_mins=15,
    purge_closed_positions_interval_mins=15,
    graceful_shutdown_on_exception=True,
)
```

---

## 7. 容器化

### 7.1 Binance 策略镜像

```dockerfile
# Dockerfile.binance
ARG NAUTILUS_IMAGE=ghcr.io/nautechsystems/nautilus_trader:latest
FROM ${NAUTILUS_IMAGE}

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

COPY strategies/ ./strategies/
COPY live_binance.py .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "live_binance.py"]
```

### 7.2 IBKR 策略镜像（含 Docker 化 Gateway）

```dockerfile
# Dockerfile.ibkr
ARG NAUTILUS_IMAGE=ghcr.io/nautechsystems/nautilus_trader:latest
FROM ${NAUTILUS_IMAGE}

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

COPY strategies/ ./strategies/
COPY live_ibkr.py .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "live_ibkr.py"]
```

### 7.3 Docker Compose 本地环境

```yaml
# docker-compose.yml
version: "3.9"

services:
  # ── Binance BTC 交易 ──
  # 实盘：BINANCE_ENV=LIVE（默认）
  # 测试网：BINANCE_ENV=TESTNET
  trader-binance:
    build:
      context: .
      dockerfile: Dockerfile.binance
    environment:
      # 通过 BINANCE_ENV 一键切换实盘/测试网
      BINANCE_ENV: ${BINANCE_ENV:-LIVE}
      # 实盘密钥
      BINANCE_API_KEY: ${BINANCE_API_KEY}
      BINANCE_API_SECRET: ${BINANCE_API_SECRET}
      # 测试网密钥（BINANCE_ENV=TESTNET 时自动读取）
      BINANCE_TESTNET_API_KEY: ${BINANCE_TESTNET_API_KEY}
      BINANCE_TESTNET_API_SECRET: ${BINANCE_TESTNET_API_SECRET}
      TRADER_ID: ${TRADER_ID:-LIVE-001}
      INSTRUMENT_ID: "BTCUSDT-PERP.BINANCE"
      TRADE_SIZE: "0.001"
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - nautilus-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "2.0"

  # ── IBKR 交易 ──
  trader-ibkr:
    build:
      context: .
      dockerfile: Dockerfile.ibkr
    environment:
      TWS_USERNAME: ${TWS_USERNAME}
      TWS_PASSWORD: ${TWS_PASSWORD}
      TWS_ACCOUNT: ${TWS_ACCOUNT}
      IBKR_MODE: ${IBKR_MODE:-paper}
      IBG_HOST: ibkr-gateway
      IBG_PORT: "4002"
    depends_on:
      - ibkr-gateway
    networks:
      - nautilus-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "2.0"

  # ── IBKR Gateway ──
  ibkr-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:stable
    environment:
      TWSUSERID: ${TWS_USERNAME}
      TWSPASSWORD: ${TWS_PASSWORD}
      TRADING_MODE: ${IBKR_MODE:-paper}
    ports:
      - "127.0.0.1:4002:4002"
      - "127.0.0.1:5900:5900"    # VNC
    networks:
      - nautilus-network
    restart: unless-stopped

  # ── Redis ──
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis-data:/data
    ports:
      - "127.0.0.1:6379:6379"
    networks:
      - nautilus-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  nautilus-network:

volumes:
  redis-data:
```

---

## 8. Kubernetes 部署

### 8.1 Binance BTC 交易 Pod

```yaml
# k8s/trader-binance.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trader-binance
  namespace: nautilus-trader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: trader-binance
  template:
    metadata:
      labels:
        app: trader-binance
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: node-type
                    operator: In
                    values: [low-latency]
      containers:
        - name: trader
          image: your-registry/trader-binance:latest
          envFrom:
            - secretRef:
                name: binance-secrets
            - configMapRef:
                name: binance-config
          resources:
            limits:
              memory: "1Gi"
              cpu: "2000m"
            requests:
              memory: "512Mi"
              cpu: "1000m"
          livenessProbe:
            exec:
              command: ["python", "-c", "import nautilus_trader; print('alive')"]
            initialDelaySeconds: 30
            periodSeconds: 30
      terminationGracePeriodSeconds: 60
```

### 8.2 IBKR 交易 Pod（含 Gateway Sidecar）

```yaml
# k8s/trader-ibkr.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trader-ibkr
  namespace: nautilus-trader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: trader-ibkr
  template:
    metadata:
      labels:
        app: trader-ibkr
    spec:
      containers:
        # 策略容器
        - name: trader
          image: your-registry/trader-ibkr:latest
          envFrom:
            - secretRef:
                name: ibkr-secrets
            - configMapRef:
                name: ibkr-config
          env:
            - name: IBG_HOST
              value: "127.0.0.1"
            - name: IBG_PORT
              value: "4002"
          resources:
            limits:
              memory: "1Gi"
              cpu: "2000m"
            requests:
              memory: "512Mi"
              cpu: "1000m"
        # IB Gateway Sidecar
        - name: ibkr-gateway
          image: ghcr.io/gnzsnz/ib-gateway:stable
          envFrom:
            - secretRef:
                name: ibkr-secrets
          ports:
            - containerPort: 4002
            - containerPort: 5900
          resources:
            limits:
              memory: "2Gi"
              cpu: "1000m"
            requests:
              memory: "1Gi"
              cpu: "500m"
      terminationGracePeriodSeconds: 60
```

### 8.3 Secret & ConfigMap

```yaml
# k8s/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: binance-secrets
  namespace: nautilus-trader
type: Opaque
stringData:
  # 实盘密钥
  BINANCE_API_KEY: "your-key"
  BINANCE_API_SECRET: "your-secret"
  # 测试网密钥（BINANCE_ENV=TESTNET 时读取）
  BINANCE_TESTNET_API_KEY: "your-testnet-key"
  BINANCE_TESTNET_API_SECRET: "your-testnet-secret"
---
apiVersion: v1
kind: Secret
metadata:
  name: ibkr-secrets
  namespace: nautilus-trader
type: Opaque
stringData:
  TWS_USERNAME: "your-ibkr-username"
  TWS_PASSWORD: "your-ibkr-password"
  TWS_ACCOUNT: "U1234567"
```

```yaml
# k8s/configmaps.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: binance-config
  namespace: nautilus-trader
data:
  # ⚠️ 切换测试网只需改这一个值：LIVE → TESTNET
  BINANCE_ENV: "LIVE"
  TRADER_ID: "LIVE-001"
  INSTRUMENT_ID: "BTCUSDT-PERP.BINANCE"
  BAR_TYPE: "BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL"
  TRADE_SIZE: "0.001"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: ibkr-config
  namespace: nautilus-trader
data:
  IBKR_MODE: "paper"
```

### 8.4 Redis StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: nautilus-trader
spec:
  serviceName: redis
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          command: ["redis-server", "--appendonly", "yes", "--maxmemory", "512mb"]
          ports:
            - containerPort: 6379
          volumeMounts:
            - name: redis-data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: redis-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 5Gi
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: nautilus-trader
spec:
  ports:
    - port: 6379
  selector:
    app: redis
```

### 8.5 NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: trader-netpol
  namespace: nautilus-trader
spec:
  podSelector:
    matchLabels:
      app: trader-binance
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - port: 6379
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443    # 交易所 API
        - port: 53     # DNS
```

---

## 9. 快速部署命令

### 9.1 Docker Compose

```bash
# ── 实盘 ──
docker compose up -d
docker compose logs -f trader-binance

# ── 测试网（只需设置 BINANCE_ENV） ──
BINANCE_ENV=TESTNET docker compose up -d trader-binance
docker compose logs -f trader-binance
```

### 9.2 Kubernetes

```bash
# 创建 Namespace 和 Secret
kubectl apply -f k8s/namespace.yaml
kubectl create secret generic binance-secrets \
  --from-literal=BINANCE_API_KEY=xxx \
  --from-literal=BINANCE_API_SECRET=yyy \
  --from-literal=BINANCE_TESTNET_API_KEY=testnet-xxx \
  --from-literal=BINANCE_TESTNET_API_SECRET=testnet-yyy \
  -n nautilus-trader

# 部署（默认实盘）
kubectl apply -f k8s/ -n nautilus-trader
kubectl logs -f deployment/trader-binance -n nautilus-trader

# ── 切换到测试网（只改 ConfigMap 一个字段） ──
kubectl set env deployment/trader-binance BINANCE_ENV=TESTNET -n nautilus-trader
# 切回实盘
kubectl set env deployment/trader-binance BINANCE_ENV=LIVE -n nautilus-trader
```

### 9.3 Helm

```bash
helm install nautilus-trader helm/nautilus-trader \
  --namespace nautilus-trader --create-namespace \
  -f production-values.yaml

# 测试网
helm upgrade nautilus-trader helm/nautilus-trader \
  --set trader.binanceEnv=TESTNET \
  -n nautilus-trader
```

---

## 10. 生产环境清单

### 10.1 上线前必做

- [ ] 策略已通过回测验证
- [ ] **策略已在 Binance 测试网完整验证**（下单→成交→平仓→对账）
- [ ] Binance 测试网验证时 `BINANCE_ENV=TESTNET`
- [ ] IBKR 先用 paper 模式验证
- [ ] API 密钥通过环境变量/K8s Secret 配置
- [ ] `manage_stop=True` 已启用

### 10.2 运行时安全

- [ ] 对账配置合理（`reconciliation_startup_delay_secs >= 10`）
- [ ] 内存清理已启用（`purge_closed_*_interval_mins`）
- [ ] IBKR Gateway `read_only_api=False`（实盘交易）
- [ ] Binance `use_reduce_only=True`（合约安全）
- [ ] `terminationGracePeriodSeconds >= 60`
- [ ] 网络策略已配置
- [ ] 有进程监控和自动重启
- [ ] 有告警通知机制
- [ ] 不要在 Jupyter Notebook 中运行实盘交易

### 10.3 Binance 实盘切换检查

- [ ] `BINANCE_ENV` 已改为 `LIVE`（测试网验证后）
- [ ] 实盘 API 密钥已配置（非测试网密钥）
- [ ] `trade_size` 已调整为实盘仓位大小
- [ ] `futures_leverages` 和 `futures_margin_types` 已确认
