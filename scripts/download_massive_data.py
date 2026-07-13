"""Download Massive.com (Polygon-compatible) historical data into the shared ParquetDataCatalog.

复用 ``trade_system_massive`` 适配器里的 REST client / 限流器 / instrument provider /
解析函数，把 Massive 的股票 K线(aggregate bars)和 instrument 定义下载到同一个固定
catalog（与 ``scripts/download_ibkr_data.py`` 共享，供回测复用）。

为什么不像 ``backtest_rsi.py`` 那样走 ``TradingNode`` + ``MassiveDataClient``？
``MassiveDataClient`` 是 ``LiveMarketDataClient`` 子类，需要一个完整的 event loop /
msgbus / cache / clock 才能实例化，对于一个只做"拉数据→落盘"的独立脚本太重。这里直接
组装适配器对外暴露的轻量组件——REST client、token-bucket 限流器、instrument
provider、``parse_bar``——同样受 429 退避保护，且无需起 node。

配置方式：只改下方「配置区」的 ``CATALOG_PATH`` / ``API_KEY`` / ``RATE_LIMIT_PER_MIN``
/ ``BAR_JOBS``，然后运行本脚本。任务列表为空即代表不下载该类数据。

前置条件
--------
1. 一个有效的 **Massive.com** API key（旧 Polygon.io key 通用）。
   通过 ``API_KEY`` 配置项或 ``MASSIVE_API_KEY`` / ``POLYGON_API_KEY`` 环境变量提供。
2. 对应定价层级的请求配额：免费层默认 5 calls/min（``RATE_LIMIT_PER_MIN`` 默认 5），
   付费层可调高；分钟线一年数据量较大，免费层会因限流而较慢。
3. 数据落盘位置：``CATALOG_PATH`` 指定目录；设为 ``None`` 则回退到
   ``NAUTILUS_PATH`` 环境变量（catalog 解析为 ``$NAUTILUS_PATH/catalog``）。

运行
----
```bash
uv run --all-packages python scripts/download_massive_data.py
```
"""

import asyncio
import datetime as dt
import os
import time
from dataclasses import dataclass

from massive.exceptions import BadResponse
from nautilus_trader.common.component import LiveClock
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from trade_system_massive.common import bar_type_to_aggs_params
from trade_system_massive.common import bar_type_to_futures_resolution
from trade_system_massive.common import date_to_str
from trade_system_massive.common import instrument_id_to_ticker
from trade_system_massive.config import MassiveDataClientConfig
from trade_system_massive.constants import DEFAULT_BASE_URL
from trade_system_massive.constants import DEFAULT_BURST
from trade_system_massive.constants import DEFAULT_RATE_LIMIT_PER_MIN
from trade_system_massive.factories import get_cached_massive_rate_limiter
from trade_system_massive.factories import get_cached_massive_rest_client
from trade_system_massive.factories import resolve_api_key
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.instruments import MassiveInstrumentProviderConfig
from trade_system_massive.parsing import parse_bar
from trade_system_massive.parsing import parse_futures_bar
from urllib3.exceptions import MaxRetryError


# ======================================================================
# 配置模型
# ======================================================================


@dataclass(frozen=True)
class MassiveConn:
    """Massive.com connection and rate-limit parameters."""

    api_key: str | None = None  # None → 回退 MASSIVE_API_KEY / POLYGON_API_KEY 环境变量
    base_url: str | None = None  # None → 默认 https://api.massive.com
    rate_limit_per_min: float = DEFAULT_RATE_LIMIT_PER_MIN  # 免费层 5；付费层可调高
    burst: int = DEFAULT_BURST  # 瞬时突发上限
    max_retries: int = 5  # BadResponse/MaxRetryError(含 429) 退避重试次数；429 需更多机会
    pagination_limit: int = 50_000  # 分页 page size（pagination=True 下控制每页大小）
    bars_timestamp_on_close: bool = True  # True=K线打 close 时间戳；False=打 open
    # 每页之间额外休眠秒数，给免费层配额留余量。0=不额外休眠。
    # rate_limit_per_min=5 时建议 0.0（页很大、一年分钟线只有几十页，单页间天然有延迟）；
    # 若遇到 429 可调高到 12.0（≈ 5 calls/min）。
    page_throttle: float = 0.0


@dataclass(frozen=True)
class BarJob:
    """A single instrument-definition and bars download job (equity or futures).

    For equities/ETFs, leave ``futures_product_code`` as None. For futures, set it
    to the Massive product code (e.g. ``"MES"``) so the provider dispatches the bare
    ticker (``MESU5``) to the futures endpoints and applies the asset-class /
    multiplier overrides from ``FUTURES_ASSET_CLASS_OVERRIDES`` / ``FUTURES_MULTIPLIERS``.
    """

    instrument_id: InstrumentId  # 如 InstrumentId(Symbol("SPY"), Venue("ARCA")) 或 (Symbol("MESU5"), Venue("XCME"))
    bar_specs: list[str]  # 如 1-MINUTE-LAST、1-DAY-LAST（仅支持外部聚合 + LAST 价）
    start: dt.date | dt.datetime  # 窗口起点；date 或 datetime，日期串交由 date_to_str 规范化
    end: dt.date | dt.datetime
    futures_product_code: str | None = None  # None=股票/ETF；非空=期货产品码（MES/ES/CL/ZN…）


@dataclass(frozen=True)
class OptionJob:
    """An option chain download job: instruments only, or instruments + bars.

    Downloads all option contracts for the underlying from Massive, parses them
    into NautilusTrader :class:`OptionContract` instruments, and writes them to
    the catalog.  Optionally also downloads OHLCV bars for each contract.

    Attributes:
        underlying: Underlying equity ticker (e.g. ``"SPY"``).
        contract_type: Filter by ``"call"`` / ``"put"`` / ``None`` (all).
        expiration_date_gte: Only contracts expiring on or after this date.
        expiration_date_lte: Only contracts expiring on or before this date.
        bar_specs: Bar specs to download per contract (e.g. ``["1-DAY-LAST"]``).
            ``None`` means only download instrument definitions, no bars.
        start: Bar time-window start (only used when ``bar_specs`` is not None).
        end: Bar time-window end (only used when ``bar_specs`` is not None).

    """

    underlying: str
    contract_type: str | None = None
    expiration_date_gte: str | None = None
    expiration_date_lte: str | None = None
    bar_specs: list[str] | None = None
    start: dt.date | dt.datetime | None = None
    end: dt.date | dt.datetime | None = None


# ======================================================================
# 配置区 —— 只改这里
# ======================================================================

# 数据落盘目录；设为 None 则回退到 NAUTILUS_PATH 环境变量。
CATALOG_PATH: str | None = r"."

CONN = MassiveConn(
    api_key=os.getenv("MASSIVE_API_KEY"),  # 设为 "xxxx" 或导出 MASSIVE_API_KEY / POLYGON_API_KEY 环境变量
    rate_limit_per_min=5,  # 免费层；付费层按档位调高以加速
)

# 近一年窗口（以脚本运行日为基准往前回溯一年）。
_today = dt.date.today()
_one_year_ago = _today.replace(year=_today.year - 1)

# 期货 product_code → Nautilus AssetClass 枚举名（未列出的产品默认 COMMODITY）。
# MES/ES 是股指期货 → EQUITY；如还下 6E(欧元) → FX、ZN(10年期) → DEBT，自行追加。
FUTURES_ASSET_CLASS_OVERRIDES: dict[str, str] = {
    "MES": "EQUITY",
    "ES": "EQUITY",
}

# 期货 product_code → 合约乘数（Massive 合约端点不暴露 multiplier）。
# MES/ES 的乘数是 5；ES 是 50。下其它产品时按合约规格补全。
FUTURES_MULTIPLIERS: dict[str, int] = {
    "MES": 5,
    "ES": 50,
}

# 股票/ETF 下载任务；留空列表则不下载。
BAR_JOBS: list[BarJob] = [
    BarJob(
        instrument_id=InstrumentId(Symbol("SPY"), Venue("ARCA")),
        # 仅支持外部聚合 + LAST 价（见 _request_bars 的校验）。
        bar_specs=["1-MINUTE-LAST", "1-HOUR-LAST", "1-DAY-LAST"],
        start=_one_year_ago,
        end=_today,
    ),
    # Micro E-mini S&P 500 期货（MES）。ticker 须带具体月份/年码（如 MESU5 = 2025-09），
    # 用 front-month（最近主力）合约；过期后请改为下一主力。venue 用 CME Globex 的 XCME。
    BarJob(
        instrument_id=InstrumentId(Symbol("MESU5"), Venue("XCME")),
        bar_specs=["1-MINUTE-LAST", "1-HOUR-LAST", "1-DAY-LAST"],
        start=_one_year_ago,
        end=_today,
        futures_product_code="MES",
    ),
]

# 期权链下载任务；留空列表则不下载。
# PMCC 策略只需 option instruments（不下 bars），用 BS 近似估算价格。
# 免费层 5 calls/min，SPY 全链数千合约，下载 bars 不现实。
OPTION_JOBS: list[OptionJob] = [
    OptionJob(
        underlying="SPY",
        expiration_date_gte="2026-01-01",
        expiration_date_lte="2027-12-31",
        # bar_specs=None → 只下 instrument 定义，不下 K线
    ),
]


# ======================================================================
# 执行逻辑 —— 一般无需改动
# ======================================================================


def _resolve_catalog(catalog_path: str | None) -> ParquetDataCatalog:
    """Return the target catalog from ``catalog_path`` or ``NAUTILUS_PATH``."""
    if catalog_path is not None:
        return ParquetDataCatalog(catalog_path)
    return ParquetDataCatalog.from_env()


def _bar_type_for(instrument_id: InstrumentId, bar_spec: str) -> BarType:
    """Parse a ``"<step>-<AGG>-<PRICE>"`` spec into a Nautilus ``BarType``."""
    step_str, agg_str, price_str = bar_spec.upper().split("-")
    spec = BarSpecification(
        int(step_str),
        BarAggregation[agg_str],
        PriceType[price_str],
    )
    return BarType(instrument_id, spec)


def _date_to_start_ns(value: dt.date | dt.datetime) -> int:
    """Coerce a date/datetime to UTC nanoseconds at start-of-day (for futures window_start)."""
    if isinstance(value, dt.datetime):
        return int(value.timestamp() * 1_000_000_000)
    d = dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    return int(d.timestamp() * 1_000_000_000)


def _fetch_aggs_in_thread(
    client,
    ticker: str,
    bar_type: BarType,
    start: dt.date | dt.datetime,
    end: dt.date | dt.datetime,
    pagination_limit: int,
    max_retries: int,
    bars_timestamp_on_close: bool,
    page_throttle: float,
    is_future: bool,
) -> list[Bar]:
    """同步拉取整段 K线并解析 (在 worker 线程中执行).

    股票/ETF 走 ``list_aggs`` (multiplier/timespan + from_/to, 毫秒时间戳);
    期货走 ``list_futures_aggregates`` (resolution 字符串 + window_start_gte/lte, 纳秒时间戳)。
    两条路径都把"构造生成器 + 完整迭代 + parse"作为一个同步块跑在线程里：翻页请求由
    SDK 内置 ``urllib3 Retry`` 自动重试 429/5xx；额外用 ``page_throttle`` 在每页之间插入
    sleep，给免费层配额留余量。

    429 可能在两层抛出：(1) SDK 内部 Retry 耗尽 → ``MaxRetryError``；(2) Massive 返回
    非 429 的错误体 → ``BadResponse``。两者都按指数退避重试整段请求，最多 ``max_retries``
    次。注意：整段重试会重复拉取已下载的 bar，但免费层 ``list_aggs`` 无 offset 分页，
    只能整段重拉；好在 429 通常在第一页就炸，重复量很小。

    注意：与适配器 ``MassiveDataClient._request_bars`` 不同，这里不经过
    ``rate_limited_call``（它只能包裹同步调用的"构造"，无法拦截惰性生成器的翻页请求）。
    对一个独立下载脚本，靠 SDK Retry + page_throttle 足够，也更直接。

    """
    last_exc: Exception | None = None
    if is_future:
        resolution = bar_type_to_futures_resolution(bar_type)
        start_ns = _date_to_start_ns(start)
        end_ns = _date_to_start_ns(end)
    else:
        multiplier, timespan = bar_type_to_aggs_params(bar_type)
        from_ = date_to_str(start)
        to = date_to_str(end)

    for attempt in range(max_retries + 1):
        try:
            bars: list[Bar] = []
            if is_future:
                aggs_iter = client.list_futures_aggregates(
                    ticker,
                    resolution=resolution,
                    window_start_gte=start_ns,
                    window_start_lte=end_ns,
                    sort="asc",
                    limit=pagination_limit,
                )
                for agg in aggs_iter:
                    bars.append(parse_futures_bar(bar_type, agg, resolution, bars_timestamp_on_close))
            else:
                # 构造惰性生成器（不发请求）；迭代时才逐页发 HTTP。
                aggs_iter = client.list_aggs(
                    ticker,
                    multiplier,
                    timespan,
                    from_,
                    to,
                    adjusted=False,
                    sort="asc",
                    limit=pagination_limit,
                )
                for agg in aggs_iter:
                    bars.append(parse_bar(bar_type, agg, multiplier, timespan, bars_timestamp_on_close))
                # 每解析一个 agg 不节流；节流以"页"为单位，靠下方 page_throttle 实现。
            # SDK 的生成器按页 yield；粗粒度节流：每消费一批后 sleep。
            # 由于无法精确感知翻页边界，这里用一个轻量近似——仅在数据量较大时按
            # pagination_limit 的粒度 sleep 一次（足够保护免费层，且不显著拖慢付费层）。
            if page_throttle > 0 and len(bars) >= pagination_limit:
                time.sleep(page_throttle)
            return bars
        except (BadResponse, MaxRetryError) as exc:
            last_exc = exc
            body = str(exc.args[0]) if exc.args else str(exc)
            is_rate_limit = "rate limit" in body.lower() or "429" in body
            if is_rate_limit or attempt < max_retries:
                # 免费层配额窗口为 60s；429 退避必须能覆盖一个完整窗口让配额回血。
                # 用 15*2**attempt、封顶 60s：15s → 30s → 60s → 60s → ...
                wait = min(60.0, 15.0 * (2.0**attempt)) if is_rate_limit else 2.0**attempt
                print(
                    f"  [bars] {type(exc).__name__} 退避 {wait:.1f}s (attempt {attempt + 1}/{max_retries + 1})",
                )
                time.sleep(wait)
                continue
            break
    assert last_exc is not None  # pragma: no cover - 循环必先置 last_exc 再 break
    raise last_exc


async def _download_bars(
    provider: MassiveInstrumentProvider,
    client,
    catalog: ParquetDataCatalog,
    job: BarJob,
    conn: MassiveConn,
) -> None:
    """Load the instrument definition, then fetch every configured bar spec into the catalog."""
    requested_id = job.instrument_id
    ticker = instrument_id_to_ticker(requested_id)
    is_future = job.futures_product_code is not None
    if is_future:
        print(f"  [dispatch] {ticker} → 期货端点 (product_code={job.futures_product_code})")
    # 落 instrument 定义（Equity 经 get_ticker_details；FuturesContract 经 list_futures_contracts；
    # 写盘供回测撮合/费用计算用）。
    await provider.load_ids_async([requested_id])
    # provider 解析 Equity 时可能用 get_ticker_details 返回的 primary_exchange 改写 venue
    # （见 instruments._parse_equity），故按 ticker 匹配而非用原始 id find，避免失配。
    instrument = next(
        (i for i in provider.get_all().values() if instrument_id_to_ticker(i.id) == ticker),
        None,
    )
    if instrument is not None:
        catalog.write_data([instrument])
        # 用解析后的真实 instrument id 构造 BarType，确保 catalog 里 instrument 与 bars
        # 的 instrument_id 完全一致（回测撮合按 instrument_id 关联）。
        bar_instrument_id = instrument.id
        print(f"  [instrument] {bar_instrument_id}")
    else:
        print(f"  [warn] 未取到 {requested_id} 的 instrument 定义，K线将沿用请求 id")
        bar_instrument_id = requested_id

    for spec_idx, bar_spec in enumerate(job.bar_specs):
        bar_type = _bar_type_for(bar_instrument_id, bar_spec)
        print(f"  [bars] {bar_instrument_id} {bar_spec}  {date_to_str(job.start)} → {date_to_str(job.end)}")
        # 整个"构造生成器 + 翻页迭代 + parse"放进一个线程：避免跨线程驱动惰性生成器，
        # 也避免在 event loop 线程里阻塞（一年分钟线可能数十万根）。
        bars = await asyncio.to_thread(
            _fetch_aggs_in_thread,
            client,
            ticker,
            bar_type,
            job.start,
            job.end,
            conn.pagination_limit,
            conn.max_retries,
            conn.bars_timestamp_on_close,
            conn.page_throttle,
            is_future,
        )
        if not bars:
            print("  [bars] 无数据返回（检查标的/权限/日期范围）")
            continue
        catalog.write_data(bars)
        print(f"  [bars] 完成，共 {len(bars)} 根")
        # 免费层配额按 60s 窗口滚动：上一个 spec 的请求（含其 429 退避重试）会把配额榨干，
        # 下一个 spec 第一页很容易撞 429。下完一个 spec 后等一个完整 60s 窗口让配额回满，
        # 最后一个 spec 无需等待。付费层可调高 rate_limit_per_min，冷却仍取满窗 60s 是保守
        # 的——若觉得过慢，可手动把这段注释掉或调小。
        if spec_idx < len(job.bar_specs) - 1:
            cooldown = 60.0
            print(f"  [bars] 等待配额回血 {cooldown:.0f}s ...")
            await asyncio.sleep(cooldown)


async def _download_option_chain(
    provider: MassiveInstrumentProvider,
    client,
    catalog: ParquetDataCatalog,
    job: OptionJob,
    conn: MassiveConn,
) -> None:
    """Download option chain instruments (and optionally bars) for one underlying."""
    underlying = job.underlying
    print(f"  [options] Loading option chain for {underlying}...")

    # Load all option contracts via the provider (which pages through list_options_contracts)
    await provider._load_option_chain(underlying)

    # Collect parsed OptionContract instruments
    all_instruments = provider.get_all().values()
    option_instruments: list[OptionContract] = []
    for inst in all_instruments:
        if not isinstance(inst, OptionContract):
            continue
        if inst.underlying != underlying:
            continue
        # Apply contract_type filter
        if job.contract_type == "call" and inst.option_kind != OptionKind.CALL:
            continue
        if job.contract_type == "put" and inst.option_kind != OptionKind.PUT:
            continue
        # Apply expiration date filters
        if job.expiration_date_gte or job.expiration_date_lte:
            expiry = unix_nanos_to_dt(inst.expiration_ns).date()
            if job.expiration_date_gte:
                gte = dt.date.fromisoformat(job.expiration_date_gte)
                if expiry < gte:
                    continue
            if job.expiration_date_lte:
                lte = dt.date.fromisoformat(job.expiration_date_lte)
                if expiry > lte:
                    continue
        option_instruments.append(inst)

    if option_instruments:
        catalog.write_data(option_instruments)
        print(f"  [options] Wrote {len(option_instruments)} option contracts for {underlying}")
    else:
        print(f"  [options] No option contracts found for {underlying}")
        return

    # Optionally download bars for each option contract
    if job.bar_specs and job.start is not None and job.end is not None:
        total_bars = 0
        for inst_idx, inst in enumerate(option_instruments):
            ticker = inst.id.symbol.value
            for _spec_idx, bar_spec in enumerate(job.bar_specs):
                bar_type = _bar_type_for(inst.id, bar_spec)
                try:
                    bars = await asyncio.to_thread(
                        _fetch_aggs_in_thread,
                        client,
                        ticker,
                        bar_type,
                        job.start,
                        job.end,
                        conn.pagination_limit,
                        conn.max_retries,
                        conn.bars_timestamp_on_close,
                        conn.page_throttle,
                        is_future=False,
                    )
                    if bars:
                        catalog.write_data(bars)
                        total_bars += len(bars)
                except Exception as exc:
                    print(f"  [options] Skipping {ticker}: {exc}")
                    continue
            # Rate limit between contracts (5 calls/min free tier)
            if inst_idx < len(option_instruments) - 1 and conn.page_throttle <= 0:
                await asyncio.sleep(12.0)  # ~5 calls/min budget
        print(f"  [options] Downloaded {total_bars} bars across {len(option_instruments)} contracts")


async def run(
    conn: MassiveConn,
    catalog_path: str | None,
    bar_jobs: list[BarJob],
    option_jobs: list[OptionJob] | None = None,
) -> None:
    """Assemble the Massive client/limiter/provider and run every configured job."""
    catalog = _resolve_catalog(catalog_path)
    print(f"[catalog] 数据将写入: {catalog.path}")

    api_key = resolve_api_key(_to_config(conn))
    if not api_key:
        raise SystemExit(
            "[error] 缺少 Massive API key：设 CONN.api_key 或导出 MASSIVE_API_KEY / POLYGON_API_KEY",
        )
    base_url = conn.base_url or DEFAULT_BASE_URL
    rate_limit_per_min = conn.rate_limit_per_min or DEFAULT_RATE_LIMIT_PER_MIN
    burst = conn.burst or DEFAULT_BURST

    rest_client = get_cached_massive_rest_client(api_key, base_url, trace=False)
    rate_limiter = get_cached_massive_rate_limiter(rate_limit_per_min, burst)
    clock = LiveClock()
    # 聚合所有期货 job 的 product_code（去 None），用于 provider 把裸期货 ticker 派发到
    # futures 端点；asset_class / multiplier overrides 来自配置区全局表。
    futures_codes = {job.futures_product_code for job in bar_jobs if job.futures_product_code}
    # 聚合所有 option job 的 underlying，用于 provider 预加载 option chain
    option_underlyings = {job.underlying for job in (option_jobs or [])} if option_jobs else set()
    provider = MassiveInstrumentProvider(
        client=rest_client,
        rate_limiter=rate_limiter,
        clock=clock,
        config=MassiveInstrumentProviderConfig(
            futures_product_codes=futures_codes or None,
            futures_asset_class_overrides=FUTURES_ASSET_CLASS_OVERRIDES or None,
            futures_multipliers=FUTURES_MULTIPLIERS or None,
            options_underlyings=option_underlyings or None,
        ),
    )
    print(f"[client] Massive REST 已就绪 ({base_url}, {rate_limit_per_min}/min, burst={burst})")
    if futures_codes:
        print(f"[client] 期货产品码: {sorted(futures_codes)}")
    if option_underlyings:
        print(f"[client] 期权标的: {sorted(option_underlyings)}")

    for job in bar_jobs:
        print(f"[job] {job.instrument_id}")
        await _download_bars(provider, rest_client, catalog, job, conn)

    for job in option_jobs or []:
        print(f"[option-job] {job.underlying}")
        await _download_option_chain(provider, rest_client, catalog, job, conn)

    print("[done] 全部下载完成")


def _to_config(conn: MassiveConn) -> MassiveDataClientConfig:
    """Build a ``MassiveDataClientConfig`` shim carrying the conn fields ``resolve_api_key`` reads."""
    return MassiveDataClientConfig(
        api_key=conn.api_key,
        base_url=conn.base_url,
        rate_limit_per_min=conn.rate_limit_per_min,
        burst=conn.burst,
        max_retries=conn.max_retries,
        pagination_limit=conn.pagination_limit,
        bars_timestamp_on_close=conn.bars_timestamp_on_close,
    )


if __name__ == "__main__":
    asyncio.run(run(CONN, CATALOG_PATH, BAR_JOBS, OPTION_JOBS))
