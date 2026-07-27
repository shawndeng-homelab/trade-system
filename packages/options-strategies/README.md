# options-strategies

Options backtesting strategies (PMCC) powered by [optopsy](https://github.com/michaeljohncarlos/optopsy).

## Installation

```bash
uv sync --all-packages
```

Requires `optopsy[data]>=2.3.0` (includes EODHD options + yfinance stock data).

## PMCC (Poor Man's Covered Call)

Long deep-ITM LEAPS call (delta ~0.8, far expiry) + short near-term OTM call (delta ~0.3).
The short call exits at 80% profit (`take_profit=0.8`) and re-enters on the next signal date.

Two independent legs are combined via `optopsy.simulate_portfolio()`:

- **LEAPS leg**: `optopsy.long_calls` with monthly entry dates
- **Short call leg**: `optopsy.short_calls` with weekly entry dates + `take_profit=0.8`

### Usage

```python
from options_strategies.pmcc import PmccConfig, run_pmcc
from options_strategies.shared import load_pmcc_data

config = PmccConfig(symbol="SPY", capital=100_000.0)
options, stock = load_pmcc_data(config.symbol)
result = run_pmcc(options, stock, config)

print(result.summary)           # dict: sharpe, sortino, win_rate, max_drawdown...
print(result.leg_results)       # per-leg SimulationResult
```

### Data

Pre-download via the `optopsy-data` CLI:

```bash
EODHD_API_KEY=... optopsy-data download SPY        # options (~730 days)
optopsy-data download SPY -s                       # stock OHLCV
```

## License

This package depends on optopsy (AGPL-3.0-or-later). If you distribute this software,
you must comply with AGPL-3.0 terms.
