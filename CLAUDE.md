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
uv run --all-packages --all-groups pytest packages/options-strategies/tests/pmcc/test_pmcc_config.py -v
```

Tests must run with `--all-packages` so workspace packages are importable.

Run the PMCC backtest:

```bash
uv run --all-packages python scripts/backtest_pmcc.py
```

Run the smoke test (synthetic data, no API key needed):

```bash
uv run --all-packages python scripts/smoke_test_pmcc.py
```

## Architecture

A monorepo with **one** uv workspace package under `packages/`, powered by [optopsy](https://github.com/michaeljohncarlos/optopsy) (pandas-vectorized options backtester):

- **`options-strategies`** — PMCC and other options strategies. Depends on `optopsy[data]>=2.3.0` (EODHD options + yfinance stock data).

### options-strategies layout

Each strategy lives in its own subpackage split into three files — **`config.py`** (a frozen pydantic `BaseModel`), **`signals.py`** (entry-date generators, pure functions), **`strategy.py`** (optopsy `simulate_portfolio` dispatch). Keeping signals engine-free means they unit-test directly:

- `pmcc/` — Poor Man's Covered Call (long deep-ITM LEAPS + short near-term OTM call). Two independent legs via `simulate_portfolio`; short call uses `take_profit=0.8` for 80%-profit early exit.
- `shared/` — data loading (`load_pmcc_data`) wrapping optopsy's `load_cached_options`/`load_cached_stocks`.

### Key patterns

- **Two-leg portfolio approach**: PMCC is decomposed into `long_calls` + `short_calls` as independent legs combined via `optopsy.simulate_portfolio()`. This is the only approach that allows the short call to independently exit at 80% profit and re-enter on the next signal date.
- **Roll = take_profit + re-entry**: optopsy has no atomic "roll" concept. Roll is expressed as `take_profit=0.8` early exit + signal-date re-entry via `entry_dates`.
- **TargetRange for delta targeting**: `TargetRange(target=0.80, min=0.75, max=0.85)` — target must be within [min, max].
- **Signals are stateless**: optopsy signals are per-bar boolean predicates. `signal_dates()` converts them to `(underlying_symbol, quote_date)` DataFrames for `entry_dates`.
- **Data via optopsy cache**: Pre-download with `optopsy-data download SPY` (options) and `optopsy-data download SPY -s` (stock). Requires `EODHD_API_KEY`.

### Key constraints

- `exit_dte < max_entry_dte` (enforced by optopsy's `StrategyParams` validator)
- `take_profit` must be `float` (e.g. `0.8`, not `1`)
- EODHD provides ~730 days of options history — sufficient for one LEAPS cycle
- optopsy is **AGPL-3.0-or-later** — distribution must comply with AGPL terms

### Conventions

- Ruff enforces `line-length = 120`, google-style docstrings, and **single-line isort imports** (`force-single-line = true`, `lines-after-imports = 2`) — one import per line, two blank lines after imports.
- **No in-function imports**: `PLC0415` is enabled; all imports go at module top-level.
- **Absolute imports**: use `from options_strategies.pmcc.config import PmccConfig`, not `from .config import PmccConfig`.
- **No `from __future__ import annotations`**: removed from all modules.

## Release

Versioning is managed by **cocogitto** (`cog.toml`) from [conventional commits](https://www.conventionalcommits.org/). It's a monorepo setup: each `[packages.*]` entry maps commit paths to per-package versions and tags. Only commits touching a registered package path trigger that package's bump. Currently registered: `options-strategies`. CHANGELOG is generated automatically — don't edit it by hand.
