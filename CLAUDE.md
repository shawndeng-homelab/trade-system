# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This is a **uv workspace**; recipes are defined in the `justfile` and run via `uvx --from rust-just just <recipe>` (or `just <recipe>` if `rust-just` is installed).

```bash
just init            # uv sync --all-packages --all-groups + install pre-commit hooks
just lint            # ruff check --fix, ruff format, ruff check (run before committing)
just test            # pytest on the dev Python (3.12)
just test-all        # pytest across the full version range (3.12–3.14)
just test-version 3.13
just docs            # mkdocs serve (local preview)
just build           # build sdist + wheel for every workspace package
```

Run a single test:

```bash
uv run --all-packages --all-groups pytest packages/trade-system-venues/tests/test_ibkr_fee.py::test_stock_tiered_per_share -v
uv run --all-packages --all-groups pytest packages/trade-system-strategies/tests/rsi/test_rsi_strategy.py::test_enter_long -v
```

Tests must run with `--all-packages` so `nautilus_trader` and the workspace packages are importable. Coverage is measured against `trade_system_core`.

Run the example backtest (writes `rsi_tearsheet.html` at repo root):

```bash
uv run --all-packages python scripts/backtest_rsi.py
```

## Architecture

A monorepo of **four** uv workspace packages under `packages/`, all targeting NautilusTrader `~=1.230.0`:

- **`trade-system-core`** — stub (`core.py` has an empty `main()`). Coverage target only.
- **`trade-system-venues`** — NautilusTrader fee and financing models for Binance and IBKR.
- **`trade-system-strategies`** — backtest trading strategies (RSI, PMCC, backspread) with shared tooling and Jupyter research. Depends on `trade-system-venues` (workspace dep).
- **`trade-system-massive`** — NautilusTrader live/historical data adapter for the Massive.com (rebranded Polygon.io) REST + WebSocket API.

### trade-system-venues layout

- `core/` — venue-agnostic abstractions. `FinancingSettlementActor` (`core/financing.py`) is a shared NautilusTrader `Actor` that settles periodic cashflows (funding, margin interest, borrow fees) into an **independent ledger without mutating account balances** — filling a gap NautilusTrader leaves in both backtest and live contexts. Venue subclasses supply the rate source and per-position formula. `core/schedule.py` holds tiered-breakpoint lookup helpers.
- `binance/` — maker/taker tiered fee model (VIP tiers, BNB discount, spot/USDⓈ-M/COIN-M) plus 8h funding settlement.
- `ibkr/` — commission model (per share / per contract, per-order min, stock value cap, Tiered vs Fixed pricing) plus margin-interest/borrow-fee financing, and `catalog_loader.py` for downloading IBKR historical data into a shared `ParquetDataCatalog`.

### trade-system-strategies layout

Each strategy lives in its own subpackage split into three files — **`config.py`** (a frozen `StrategyConfig`), **`signals.py`** (the decision state machine, pure functions), **`strategy.py`** (the NautilusTrader `Strategy` glue). Keeping signals engine-free means they unit-test directly and reuse in research notebooks:

- `rsi/` — RSI double-touch mean-reversion on hourly bars. The only fully-wired strategy; entry sizes via fractional Kelly from rolling realized PnL.
- `pmcc/` — Poor Man's Covered Call (long deep-ITM LEAPS + short near-term OTM call). Scaffold — `on_option_chain`/submit/reconcile stubbed.
- `backspread/` — Call backspread (sell 1 ATM/ITM, buy 2 OTM, same expiry). Scaffold.
- `shared/` — strategy-agnostic tooling reused across all strategies:
  - `legs.py` — `LegGroup` multi-leg position state machine. NautilusTrader has no native client-side combo order for backtests, so each leg is a separate order reconciled here.
  - `selection.py` — option-leg selection (strike/DTE/delta/OI filters); `select_short_option` ports thetagang's `OptionChainScanner.find_eligible_contracts`.
  - `management.py` — roll/close decision rules, ported from thetagang's `options_engine` as pure functions over a position snapshot.
  - `sizing.py` — Kelly-criterion sizing + rolling realized-PnL accumulator (`TradeStats`).
  - `greeks.py`, `data.py` — greek math and catalog IO.
- `research/` — `analyze.py` plus `.ipynb` notebooks (the `[research]` extra installs jupyterlab/matplotlib).

### trade-system-massive layout

NautilusTrader `LiveDataClient` adapter for Massive.com (= rebranded Polygon.io; existing Polygon keys work unchanged).

- `config.py` (`MassiveDataClientConfig`), `constants.py`, `common.py` (ticker↔InstrumentId, venue, bar-type→aggs params, ms↔ns), `parsing.py` (Massive response models → Nautilus `TradeTick`/`QuoteTick`/`Bar`; note aggregate timestamps are **ms** while others are **ns**).
- `rate_limiter.py` — async `TokenBucketRateLimiter` (token bucket with HTTP 429 backoff) plus `rate_limited_call(limiter, fn, *args, **kw)`, the shared acquire→`asyncio.to_thread`→429-retry helper. **The Massive `RESTClient` is synchronous urllib3; every REST call goes through this wrapper** rather than patching the third-party client. `BadResponse` carries only body text (no status code), so 429 detection inspects the body for `"rate limit"`/`"429"`.
- `instruments.py` — `MassiveInstrumentProvider(InstrumentProvider)` + `MassiveInstrumentProviderConfig`. Loading is **on-demand-first**: `load_ids_async` resolves each id individually (equity→`get_ticker_details`, option→`get_options_contract`); full option-chain preload via `config.options_underlyings` only when explicitly configured (free-tier friendly).
- `data_client.py` — `MassiveDataClient(LiveMarketDataClient)`. Implements `_request_trade_ticks`/`_request_quote_ticks` (ns start/end → ms `timestamp_gte`/`timestamp_lte`), `_request_bars` (guards external+LAST aggregation; `bar_type_to_aggs_params`), `_request_instrument(s)`, and `_request_order_book_snapshot` (last-quote → `OrderBookDelta` CLEAR+SET, since NautilusTrader has no `_handle_order_book_snapshot` callback).
- `factories.py` — `MassiveLiveDataClientFactory(LiveDataClientFactory)`; `create` wires the provider's `load_all`/`load_ids` via `MassiveInstrumentProviderConfig`. lru-cached REST client / limiter / provider. API key resolves from config → `MASSIVE_API_KEY` → legacy `POLYGON_API_KEY`.

**v1 = historical REST only** — `subscribe_*`/`unsubscribe_*` raise `NotImplementedError("...is planned for v2")`; real-time WebSocket is stubbed for v2. Known approximations flagged as TODOs: instruments assume a `$0.01` price increment (Massive exposes no tick-size field) and `activation_ns = expiration_ns − 90d` (matches the IBKR adapter convention; replace with a real listing/activation date when Massive exposes one). `tests/` covers instrument parsing (`SimpleNamespace` fakes, no network) and the rate-limiter retry path.

### Key patterns

- **Fee models** subclass `nautilus_trader.backtest.models.FeeModel` with a paired `FeeModelConfig` subclass (`frozen=True`). This lets them plug into `BacktestEngine.add_venue(fee_model=...)` directly *and* be referenced by path via `ImportableFeeModelConfig` in the high-level `BacktestNode` API. `get_commission` is called once per fill; IBKR's per-order minimum is approximated by applying it only when `order.filled_qty == 0` (first fill).
- **Strategies** are referenced by path in backtest run configs via `ImportableStrategyConfig` (`strategy_path="...strategy:RsiStrategy"`, `config_path="...config:RsiConfig"`) — see `scripts/backtest_rsi.py`.
- **Schedules as data**: commission/fee rate tables live in `schedule.py` modules as plain `Decimal` dicts/tuples so they are easy to audit and adjust to account tier/region. Keep monetary math in `Decimal`, never float.
- **Implementation status varies** — `ibkr.fee`/`ibkr.catalog_loader` and the RSI strategy are implemented; `binance.fee`, the financing actors, `core/schedule`, and the PMCC/backspread strategies still have `raise NotImplementedError(...)` / `# TODO` scaffold methods. Check each package's README status table before assuming a method works.

### Conventions

- Ruff enforces `line-length = 120`, google-style docstrings, and **single-line isort imports** (`force-single-line = true`, `lines-after-imports = 2`) — one import per line, two blank lines after imports.
- **No in-function imports**: `PLC0415` is enabled; all imports go at module top-level. IBKR support (`ibapi`, etc.) ships via the `nautilus-trader[ib]` extra so those imports are safe at top level.
- `NAUTILUS_PATH` env var sets the shared data-catalog root; `catalog_loader.default_catalog()` resolves to `$NAUTILUS_PATH/catalog`. Both `scripts/download_ibkr_data.py` (download) and `scripts/backtest_rsi.py` (read) share this store — set it once.

## Release

Versioning is managed by **cocogitto** (`cog.toml`) from [conventional commits](https://www.conventionalcommits.org/). It's a monorepo setup: each `[packages.*]` entry maps commit paths to per-package versions and tags. Only commits touching a registered package path trigger that package's bump. Currently registered: `trade-system-core`, `trade-system-venues`, `trade-system-strategies` — **`trade-system-massive` is not yet registered in `cog.toml`**, so commits under `packages/trade-system-massive/` won't trigger a version bump until added. CHANGELOG is generated automatically — don't edit it by hand.
