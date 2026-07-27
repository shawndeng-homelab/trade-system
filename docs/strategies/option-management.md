# PMCC (Poor Man's Covered Call)

The `options-strategies` package implements PMCC as two independent single-leg
strategies combined via `optopsy.simulate_portfolio()`.

## Architecture

PMCC decomposes into:

| Leg | Strategy | Entry signal | Exit |
|-----|----------|-------------|------|
| **LEAPS** | `optopsy.long_calls` | Monthly (first trading day) | DTE ≤ `leaps_exit_dte` |
| **Short call** | `optopsy.short_calls` | Weekly (first trading day) | DTE ≤ `short_exit_dte` **or** 80% profit (`take_profit=0.8`) |

The short call's "roll" is expressed as **take_profit early exit + signal-date re-entry**,
not as an atomic close+open action. This is the only approach that allows the short call
to independently cycle while the LEAPS holds.

## Configuration — `PmccConfig`

```python
from options_strategies.pmcc import PmccConfig

config = PmccConfig(
    symbol="SPY",
    capital=100_000.0,
    # LEAPS: deep-ITM, far expiry
    leaps_delta=0.80,           # target delta
    leaps_delta_min=0.75,       # TargetRange min
    leaps_delta_max=0.85,       # TargetRange max
    leaps_max_entry_dte=365,    # far month
    leaps_exit_dte=30,          # exit when DTE drops below this
    # Short call: near-term, 80% profit exit
    short_delta=0.30,
    short_delta_min=0.25,
    short_delta_max=0.35,
    short_max_entry_dte=45,     # near term
    short_exit_dte=7,
    short_take_profit=0.8,      # 80% profit → exit
    # Portfolio weights
    leaps_weight=0.6,
    short_weight=0.4,
)
```

### Key constraints

- `exit_dte < max_entry_dte` (enforced by optopsy's `StrategyParams` validator)
- `take_profit` must be `float` (e.g. `0.8`, not `1`)
- `TargetRange` requires `min ≤ target ≤ max`

## Entry signals — `pmcc/signals.py`

Each leg has independent entry-date generators producing `(underlying_symbol, quote_date)` DataFrames:

| Method | Leg | Description |
|--------|-----|-------------|
| `monthly_start` | LEAPS | First trading day of each month |
| `weekly_start` | Short call | First trading day of each week |
| `iv_rank_above` | Short call | Enter when IV rank exceeds threshold (uses optopsy's built-in signal) |

Custom signals can be composed via optopsy's `&`/`|` operators or `custom_signal()`.

## Data — `shared/data.py`

Thin wrapper around optopsy's parquet cache:

```python
from options_strategies.shared import load_pmcc_data

options, stock = load_pmcc_data("SPY", start_date="2024-01-01", expiration_type="monthly")
```

Pre-download required:

```bash
EODHD_API_KEY=... optopsy-data download SPY        # options
optopsy-data download SPY -s                       # stock OHLCV
```

EODHD provides ~730 days of options history — sufficient for one LEAPS cycle.

## Limitations

1. **Independent capital allocation**: `simulate_portfolio` allocates `capital × weight` per leg independently. It does not model PMCC's real margin efficiency (LEAPS substitutes 100 shares).
2. **Short call is "naked" in simulation**: The short call leg runs as an independent `short_calls` strategy. P&L is additive across legs, which matches real PMCC economics, but margin/capital efficiency differs.
3. **EODHD data depth**: ~730 days. Acceptable for one LEAPS cycle; insufficient for multi-year studies.
4. **No combo margin**: optopsy does not model portfolio margin. Capital is split by weight, not by real buying-power reduction.
