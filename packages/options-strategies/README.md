# options-strategies

Options backtesting strategies (PMCC, 0DTE Iron Condor, Benchmark) powered by [optopsy](https://github.com/michaeljohncarlos/optopsy).

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

## 0DTE Iron Condor

Near-expiry iron condor (4 legs: long put wing + short put + short call + long call wing).
Enter 1–14 DTE, exit at or near expiration, capturing rapid time decay.

### Usage

```python
from options_strategies.odte_iron_condor import OdteIronCondorConfig, run_odte_iron_condor
from options_strategies.shared import load_odte_data

config = OdteIronCondorConfig(symbol="SPY", capital=100_000.0, symbols=["SPY", "QQQ", "IWM"])
options, stock = {}, {}
for sym in config.symbols:
    opts, stk = load_odte_data(sym)
    options[sym] = opts
    stock[sym] = stk
result = run_odte_iron_condor(options, stock, config)
```

## Benchmark (Rolling ATM Call)

Buy ATM call (delta ~0.50), hold until DTE drops to 150, close and immediately buy the next ATM call.
Repeat until the backtest end date. Each symbol (SPY, QQQ, IWM) runs as an independent leg.

The rolling behavior is achieved by providing every trading day as `entry_dates` combined with `max_positions=1`:
optopsy enters on the first available date, exits when DTE hits `exit_dte`, and re-enters on the next trading day.

### Usage

```python
from options_strategies.benchmark import BenchmarkConfig, run_benchmark
from options_strategies.shared import load_benchmark_data

config = BenchmarkConfig(symbols=["SPY", "QQQ", "IWM"])
options, stock = {}, {}
for sym in config.symbols:
    opts, stk = load_benchmark_data(sym)
    options[sym] = opts
    stock[sym] = stk
result = run_benchmark(options, stock, config)

# Use with BacktestReport for equity curve overlay and summary comparison
from backtest_charts import BacktestReport
report = BacktestReport(
    strategy_result,
    capital=100_000,
    benchmark_results={"Rolling ATM Call": result},
)
report.plot_equity()   # benchmark equity curve overlaid as dashed line
report.plot_summary()  # benchmark metrics shown side-by-side
```

## Data

Pre-download via the `optopsy-data` CLI:

```bash
EODHD_API_KEY=... optopsy-data download SPY        # options (~730 days)
optopsy-data download SPY -s                       # stock OHLCV
optopsy-data download QQQ                          # options (optional)
optopsy-data download QQQ -s                       # stock OHLCV (optional)
optopsy-data download IWM                          # options (optional)
optopsy-data download IWM -s                       # stock OHLCV (optional)
```

## License

This package depends on optopsy (AGPL-3.0-or-later). If you distribute this software,
you must comply with AGPL-3.0 terms.
