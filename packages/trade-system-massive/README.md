# trade-system-massive

A NautilusTrader data adapter for the [Massive.com](https://massive.com) REST + WebSocket API.

Massive.com is the rebranded Polygon.io API (2025-10-30). Existing Polygon API keys,
accounts, and integrations continue to work unchanged.

## Status

**v1 — historical REST only.**

- [x] Instrument loading: equities (`Equity`), options (`OptionContract`), and futures (`FuturesContract`)
- [x] Historical trade ticks (`list_trades` / `list_futures_trades`)
- [x] Historical quote ticks (`list_quotes` / `list_futures_quotes`)
- [x] Historical bars (`list_aggs` / `list_futures_aggregates`)
- [x] Order book snapshot from last quote (`get_last_quote` / `get_futures_snapshot`)
- [x] Configurable token-bucket rate limiter with HTTP 429 backoff
- [ ] Real-time WebSocket streaming (stubbed for v2)

> **Historical-only:** the `subscribe_*` / `unsubscribe_*` family raises
> `NotImplementedError("... is planned for v2")`. Real-time streaming lands in v2.

## Installation

This is a `uv` workspace package. From the `trade-system` root:

```bash
uv sync --all-packages
```

## Usage

Register the client on a `TradingNodeConfig` via `ImportableConfig` — no changes to
Nautilus are required:

```python
from nautilus_trader.config import ImportableConfig
from nautilus_trader.common.config import ImportableFactoryConfig

data_clients = {
    "MASSIVE": ImportableConfig(
        path="trade_system_massive.config:MassiveDataClientConfig",
        config={
            "api_key": None,                # falls back to MASSIVE_API_KEY env var
            "rate_limit_per_min": 5,        # free tier; raise for paid tiers
            "instrument_ids": ["AAPL.XNAS"],
            "options_underlyings": ["AAPL"],
        },
        factory=ImportableFactoryConfig(
            path="trade_system_massive.factories:MassiveLiveDataClientFactory",
        ),
    ),
}
```

## Futures

Futures use a separate Massive endpoint family (`/futures/v1/...`) with different
param models and nanosecond (not millisecond) aggregate timestamps, so they are
dispatched separately. Because futures tickers are bare (e.g. `ESZ4`) with no
prefix, the adapter cannot distinguish them from stocks by string alone — you
must register the product codes you trade via `futures_product_codes`:

```python
data_clients = {
    "MASSIVE": ImportableConfig(
        path="trade_system_massive.config:MassiveDataClientConfig",
        config={
            "futures_product_codes": {"ES", "CL", "ZN"},   # dispatch + preload
            "futures_asset_class_overrides": {              # default is COMMODITY
                "ES": "EQUITY",
                "6E": "FX",
                "ZN": "DEBT",
            },
            "futures_multipliers": {"ES": 50, "CL": 1000},  # Massive exposes none
        },
        factory=ImportableFactoryConfig(
            path="trade_system_massive.factories:MassiveLiveDataClientFactory",
        ),
    ),
}
```

v1 limits to keep in mind:

- **Single contracts only.** `type='combo'` (spread) contracts are skipped with a
  warning; `NautilusTrader` `FuturesSpread` is out of scope for v1.
- **Contract multiplier defaults to 1.** Massive's contract endpoint does not expose
  the multiplier (e.g. ES=50, CL=1000); override per product via `futures_multipliers`.
- **Asset class defaults to `COMMODITY`.** Override per product via
  `futures_asset_class_overrides` (values are enum *names* like `"EQUITY"`/`"FX"`).
- **Daily bars map to `1session`.** Massive has no `day` unit, so a Nautilus
  1-day bar requests one trading session. With `bars_timestamp_on_close=True`,
  only fixed-duration resolutions (sec/min/hour) advance to the close; session and
  longer stay on the open (with a warning log).

## Free tier rate limits

The Massive free tier enforces a per-minute request budget. The adapter gates every
REST call through a token-bucket limiter (`rate_limit_per_min`, default `5`) and backs
off on HTTP 429 responses. Adjust `rate_limit_per_min` / `burst` to match your tier.
