# trade-system-massive

A NautilusTrader data adapter for the [Massive.com](https://massive.com) REST + WebSocket API.

Massive.com is the rebranded Polygon.io API (2025-10-30). Existing Polygon API keys,
accounts, and integrations continue to work unchanged.

## Status

**v1 — historical REST only.**

- [x] Instrument loading: equities (`Equity`) and options (`OptionContract`)
- [x] Historical trade ticks (`list_trades`)
- [x] Historical quote ticks (`list_quotes`)
- [x] Historical bars (`list_aggs`)
- [x] Order book snapshot from last quote (`get_last_quote`)
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

## Free tier rate limits

The Massive free tier enforces a per-minute request budget. The adapter gates every
REST call through a token-bucket limiter (`rate_limit_per_min`, default `5`) and backs
off on HTTP 429 responses. Adjust `rate_limit_per_min` / `burst` to match your tier.
