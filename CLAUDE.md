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
```

Tests must run with `--all-packages` so `nautilus_trader` and the workspace packages are importable. Coverage is measured against `trade_system_core`.

## Architecture

Two workspace packages under `packages/`:

- **`trade-system-core`** — currently a stub (`core.py` has an empty `main()`).
- **`trade-system-venues`** — the substantive package: NautilusTrader fee and financing models for Binance and IBKR.

### trade-system-venues layout

- `core/` — venue-agnostic abstractions. `FinancingSettlementActor` (in `core/financing.py`) is a shared NautilusTrader `Actor` that settles periodic cashflows (funding, margin interest, borrow fees) into an **independent ledger without mutating account balances** — filling a gap NautilusTrader leaves in both backtest and live contexts. Venue subclasses supply the rate source and per-position formula. `core/schedule.py` holds tiered-breakpoint lookup helpers.
- `binance/` — maker/taker tiered fee model (VIP tiers, BNB discount, spot/USDⓈ-M/COIN-M) plus 8h funding settlement.
- `ibkr/` — commission model (per share / per contract, per-order min, stock value cap, Tiered vs Fixed pricing) plus margin-interest/borrow-fee financing, and `catalog_loader.py` for downloading IBKR historical data into a shared `ParquetDataCatalog`.

### Key patterns

- **Fee models** subclass `nautilus_trader.backtest.models.FeeModel` with a paired `FeeModelConfig` subclass (`frozen=True`). This lets them plug into `BacktestEngine.add_venue(fee_model=...)` directly *and* be referenced by path via `ImportableFeeModelConfig` in the high-level `BacktestNode` API. `get_commission` is called once per fill; IBKR's per-order minimum is approximated by applying it only when `order.filled_qty == 0` (first fill).
- **Schedules as data**: commission/fee rate tables live in `schedule.py` modules as plain `Decimal` dicts/tuples so they are easy to audit and adjust to account tier/region. Keep monetary math in `Decimal`, never float.
- **Implementation status varies** — `ibkr.fee` and `ibkr.catalog_loader` are implemented; `binance.fee`, the financing actors, and `core/schedule` still have `raise NotImplementedError(...)` scaffold methods. Check the README status table before assuming a method works.

### Conventions

- Ruff enforces `line-length = 120`, google-style docstrings, and **single-line isort imports** (`force-single-line = true`) — one import per line, two blank lines after imports.
- **No in-function imports**: `PLC0415` is enabled; all imports go at module top-level. IBKR support (`ibapi`, etc.) ships via the `nautilus-trader[ib]` extra so those imports are safe at top level.
- `NAUTILUS_PATH` env var sets the shared data-catalog root; `catalog_loader.default_catalog()` resolves to `$NAUTILUS_PATH/catalog`.

## Release

Versioning is managed by **cocogitto** (`cog.toml`) from [conventional commits](https://www.conventionalcommits.org/). It's a monorepo setup: each `[packages.*]` entry maps commit paths to per-package versions and tags. Only commits touching a registered package path trigger that package's bump. CHANGELOG is generated automatically — don't edit it by hand.
