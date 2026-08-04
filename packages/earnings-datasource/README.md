# earnings-datasource

Earnings calendar data source for the `optopsy` options backtester.

This package wraps vendor APIs (currently EODHD; Unusual Whales and
SEC EDGAR are planned) and normalizes their raw responses into a single
`EarningsEvent` schema. Cached results live at
`$OPTOPSY_DATA_DIR/cache/earnings/{SYMBOL}.parquet` so downstream
strategies can join earnings dates to options chains with zero
network access.

## Features

- **Unified schema** — One `EarningsEvent` model regardless of vendor.
  Fields: `code`, `symbol`, `report_date`, `fiscal_period_end`,
  `session` (`bmo` / `amc` / `unknown`), `estimate_eps`, `actual_eps`,
  `eps_surprise`, `eps_surprise_pct`, `currency`, `source`.
- **EODHD integration** — Full client for the
  [EODHD Corporate Events Calendar & News API](https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits)
  with 30-day windowed pagination, 429/5xx retry, and token redaction.
- **Pluggable** — Registers itself with optopsy via the
  `optopsy.providers` entry point; optopsy auto-discovers the
  `fetch_earnings_calendar` chat tool.
- **Optional optopsy dependency** — `optopsy` is loaded lazily inside
  the entry point so the package works fine without it; you can also
  install the `optopsy` extra for full integration.
- **AGPL-3.0-or-later** — Same license as optopsy.

## Installation

Add to the workspace:

```bash
just add-package earnings-datasource
```

Then `uv sync --all-packages --all-groups`.

Set the API token (project root `.env`):

```bash
EODHD_API_KEY=<your_token>
```

The token is the same one used for `optopsy-data download`. To fetch
earnings calendar data you need the **Corporate Events Calendar &
News API** plan on top of the standard plan — see
[the pricing page](https://eodhd.com/pricing).

## Quick start

```python
from datetime import date
from earnings_datasource import EarningsCalendar, EodhdEarningsProvider

provider = EodhdEarningsProvider()  # uses EODHD_API_KEY
events = provider.fetch(["AAPL", "MSFT"], date(2024, 1, 1), date(2024, 3, 31))
df = EarningsCalendar(events=events).to_dataframe()
print(df.head())
```

## CLI

A Click-based console script is registered as `earnings-data`. It
mirrors the layout of `optopsy-data`: a top-level group with
`download` and `cache` subcommands.

`download` is **incremental by default** — it inspects each symbol's
local cache and only queries the API for rows newer than
`(max cached report_date - overlap-days)`. Symbols with no cache fall
back to a 2-year backfill (override with `--no-cache-window-days`).
Pass `--full` to force a full re-fetch of the requested date window
(useful when you want to refresh a stale range or pull data into a
fresh cache).

```bash
# Show the full surface
earnings-data --help

# Default: incremental — first run pulls 1 year, later runs fill gaps
just download-earnings --symbols AAPL,MSFT,GOOGL

# Force a full re-fetch over an explicit window
just download-earnings --full --symbols AAPL --from 2024-01-01 --to 2024-03-31

# Custom cache directory (otherwise uses $OPTOPSY_DATA_DIR or ~/.optopsy)
just download-earnings --symbols AAPL --cache-dir ./tmp/cache
```

The `cache` subcommand mirrors `optopsy-data cache`:

```bash
earnings-data cache size       # per-symbol + total disk usage
earnings-data cache clear AAPL # remove one symbol
earnings-data cache clear --all -y  # nuke everything
```

`download` prints a Rich progress bar (or per-window lines in
non-TTY contexts) and a final summary table of the events fetched.

## Reading cached data

```python
from earnings_datasource.providers.store import read_earnings

df = read_earnings("AAPL.US")
print(df.head())
```

The DataFrame has the canonical column order (one row per earnings
announcement):

| column | type | meaning |
|---|---|---|
| `code` | str | EODHD native code, e.g. `AAPL.US` |
| `symbol` | str | Bare ticker, e.g. `AAPL` |
| `report_date` | `pd.Timestamp` | Naive UTC midnight — canonical join key |
| `report_date_utc` | `pd.Timestamp` | Tz-aware datetime of the announcement |
| `fiscal_period_end` | `date` | End of the fiscal period the report covers |
| `session` | str | `bmo` / `amc` / `unknown` |
| `estimate_eps` | float | Consensus EPS estimate |
| `actual_eps` | float | Reported EPS |
| `eps_surprise` | float | `actual_eps - estimate_eps` |
| `eps_surprise_pct` | float | Surprise as a fraction (`0.05` = 5%) |
| `currency` | str | `USD` / `EUR` / etc. |
| `source` | str | `eodhd` (forward-compat with other vendors) |

## Architecture

```
src/earnings_datasource/
├── __init__.py        # public API re-exports
├── cli.py             # Click-based earnings-data console script
├── models.py          # EarningsEvent + EarningsCalendar (Pydantic v2 frozen)
├── providers/
│   ├── base.py        # BaseEarningsProvider ABC
│   ├── eodhd.py       # EodhdEarningsProvider
│   └── store.py       # parquet cache helpers
└── entry_point.py     # optopsy.providers plugin adapter
```

### Why a custom cache instead of `optopsy.get_store()`?

optopsy's `PostgresStore` is hard-coded to two table names
(`options_data` and `stocks_data`); an `"earnings"` category would
`KeyError` on insert. The package uses plain `pd.read_parquet` /
`pd.to_parquet` at `$OPTOPSY_DATA_DIR/cache/earnings/` instead, which
keeps optopsy a weak (plugin-entry-point) dependency rather than a
strong runtime one.

### Adding new providers

1. Subclass `BaseEarningsProvider` (3 abstract methods: `fetch`,
   `normalize_symbol`, `cache_key`).
2. Map your vendor's response to `EarningsEvent.model_validate(...)`.
3. Optionally implement `incremental_fetch(...)` for cache-aware
   refresh; the `download` subcommand dispatches to it by default
   (so re-running only fetches rows newer than the local cache).
4. Add the class to `_PROVIDERS` in `cli.py` — the CLI's
   `--source` choices auto-pick it up. No `optopsy.providers`
   plumbing required for non-`optopsy` consumers.

## Tests

```bash
just test  # full suite, including 60+ unit tests for this package
```

Integration test (`tests/test_integration.py`) makes a real EODHD call
when `EODHD_API_KEY` is set; CI without the key skips it automatically.

## License

AGPL-3.0-or-later. Inherits the AGPL surface from optopsy via the
`optopsy.providers` entry point — see `optopsy`'s license for
distribution implications.
