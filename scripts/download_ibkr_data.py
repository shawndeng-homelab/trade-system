"""Download IBKR historical data into the shared ParquetDataCatalog.

使用 ``trade_system_venues.ibkr.catalog_loader`` 把 IBKR 的股票/ETF K线数据和
期权链合约定义下载到同一个固定 catalog（供回测复用）。

配置方式：只改下方「配置区」的 ``CONN`` / ``CATALOG_PATH`` / ``BAR_JOBS`` /
``OPTION_JOBS``，然后运行本脚本。任务列表为空即代表不下载该类数据。

前置条件
--------
1. 一个正在运行、且脚本可连接的 **TWS** 或 **IB Gateway**
   （端口：7497 纸上交易 TWS / 7496 实盘 TWS / 4001、4002 网关）。
2. 拥有所请求标的的 IBKR 行情权限（回测通常用延迟数据即可）。
3. 数据落盘位置：``CATALOG_PATH`` 指定目录；设为 ``None`` 则回退到
   ``NAUTILUS_PATH`` 环境变量（catalog 解析为 ``$NAUTILUS_PATH/catalog``）。

运行
----
```bash
uv run --all-packages python scripts/download_ibkr_data.py
```
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from trade_system_venues.ibkr import catalog_loader as cl


# ======================================================================
# 配置模型
# ======================================================================


@dataclass(frozen=True)
class IBConn:
    """TWS / IB Gateway connection parameters."""

    host: str = "127.0.0.1"
    port: int = 4001  # 7497 纸上 TWS / 7496 实盘 TWS / 4001、4002 网关
    client_id: int = 5  # 每个并发连接必须唯一
    delayed_data: bool = True  # True=延迟行情(回测够用)，False=实时行情


@dataclass(frozen=True)
class BarJob:
    """A single stock/ETF instrument-definition and bars download job."""

    instrument_ids: list[str]
    bar_specs: list[str]  # 如 1-DAY-LAST、1-HOUR-LAST、1-MINUTE-LAST
    start: datetime
    end: datetime
    use_rth: bool = True  # 仅取常规交易时段


@dataclass(frozen=True)
class OptionJob:
    """A single option-chain instrument-definition download job (definitions only)."""

    underlying: str
    primary_exchange: str
    min_expiry_days: int = 7
    max_expiry_days: int = 30


# ======================================================================
# 配置区 —— 只改这里
# ======================================================================

# 数据落盘目录；设为 None 则回退到 NAUTILUS_PATH 环境变量。
CATALOG_PATH: str | None = r"."

CONN = IBConn(host="192.168.88.56", port=4001, client_id=5)

# 股票/ETF 下载任务；留空列表则不下载股票数据。
BAR_JOBS: list[BarJob] = [
    BarJob(
        instrument_ids=["SPY.ARCA"],
        # LAST=成交价；分钟级额外拉 BID/ASK 买卖价(回测撮合/价差用)。
        # 需要中间价可加 1-MINUTE-MID；需要日线/小时线的买卖价可自行加 -BID/-ASK。
        bar_specs=[
            "1-DAY-LAST",
            "1-HOUR-LAST",
            # "1-MINUTE-LAST",
            # "1-MINUTE-BID",
            # "1-MINUTE-ASK",
        ],
        start=datetime(2026, 1, 1),
        end=datetime(2026, 6, 30),
        use_rth=False,  # False=含盘前盘后；True=仅常规交易时段
    ),
]

# 期权链下载任务；暂不拉期权 → 留空列表。策略需要期权时，往这里加 OptionJob(...)：
#   OptionJob(underlying="SPY", primary_exchange="ARCA", min_expiry_days=7, max_expiry_days=30)
OPTION_JOBS: list[OptionJob] = []


# ======================================================================
# 执行逻辑 —— 一般无需改动
# ======================================================================


def _resolve_catalog(catalog_path: str | None) -> ParquetDataCatalog:
    """Return the target catalog from ``catalog_path`` or ``NAUTILUS_PATH``."""
    if catalog_path is not None:
        return ParquetDataCatalog(catalog_path)
    return cl.default_catalog()


async def run(
    conn: IBConn,
    catalog_path: str | None,
    bar_jobs: list[BarJob],
    option_jobs: list[OptionJob],
) -> None:
    """Connect to IBKR and run every configured bar and option-chain job."""
    catalog = _resolve_catalog(catalog_path)
    print(f"[catalog] 数据将写入: {catalog.path}")

    client = await cl.make_client(
        host=conn.host,
        port=conn.port,
        client_id=conn.client_id,
        delayed_data=conn.delayed_data,
    )
    print(f"[client] 已连接 {conn.host}:{conn.port} (client_id={conn.client_id})")

    for job in bar_jobs:
        print(f"[stock] 下载 {job.instrument_ids} 的 {job.bar_specs} ...")
        await cl.download_stock_bars(
            client,
            catalog,
            instrument_ids=job.instrument_ids,
            bar_specifications=job.bar_specs,
            start=job.start,
            end=job.end,
            use_rth=job.use_rth,
        )
        print("[stock] 完成")

    for job in option_jobs:
        print(f"[option] 下载 {job.underlying} 期权链 (主交易所 {job.primary_exchange}) ...")
        await cl.download_option_chain(
            client,
            catalog,
            underlying=job.underlying,
            primary_exchange=job.primary_exchange,
            min_expiry_days=job.min_expiry_days,
            max_expiry_days=job.max_expiry_days,
        )
        print("[option] 完成")

    print("[done] 全部下载完成")


if __name__ == "__main__":
    asyncio.run(run(CONN, CATALOG_PATH, BAR_JOBS, OPTION_JOBS))
