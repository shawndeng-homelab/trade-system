# backtest-charts

Plotly visualizations for optopsy backtest results — equity curve, P&L analysis, exit breakdown, and strategy summary.

## Install

```bash
pip install backtest-charts
```

## Quick Start

```python
from backtest_charts import BacktestReport

# Create a report from any duck-typed result object
# (e.g. optopsy.PortfolioResult)
report = BacktestReport(result, capital=100_000)

# Individual charts — each returns a go.Figure (renders in Jupyter)
report.plot_equity()       # Equity curve with starting-capital reference line
report.plot_cum_pnl()      # Cumulative P&L by leg
report.plot_pnl_dist()     # Per-trade P&L distribution (green/crimson bars)
report.plot_exits()        # Exit type breakdown by leg
report.plot_summary()      # Strategy metrics table

# Full dashboard (2-column grid of all panels)
report.plot_dashboard()

# Save to HTML
report.save_html("backtest_dashboard.html")
```

## Benchmark Comparison

Overlay benchmark strategy equity curves and compare metrics side-by-side:

```python
from options_strategies.benchmark import BenchmarkConfig, run_benchmark
from options_strategies.shared import load_benchmark_data

# Run a rolling ATM call benchmark
bm_config = BenchmarkConfig(symbols=["SPY", "QQQ", "IWM"])
bm_options, bm_stock = {}, {}
for sym in bm_config.symbols:
    opts, stk = load_benchmark_data(sym)
    bm_options[sym] = opts
    bm_stock[sym] = stk
bm_result = run_benchmark(bm_options, bm_stock, bm_config)

# Create report with benchmark overlay
report = BacktestReport(
    result,
    capital=100_000,
    benchmark_results={"Rolling ATM Call": bm_result},
)

report.plot_equity()   # benchmark equity curve overlaid as dashed line
report.plot_summary()  # benchmark metrics shown side-by-side with strategy
```

### Stock Price Overlay

Overlay underlying stock prices on a secondary y-axis:

```python
report = BacktestReport(
    result,
    capital=100_000,
    stock_data={"SPY": spy_df, "QQQ": qqq_df},
)
report.plot_equity()  # stock prices shown as dotted lines on secondary axis
```

### Summary Table Benchmarks

Add buy-and-hold ATM call returns to the summary table (legacy, single return per symbol):

```python
report = BacktestReport(
    result,
    capital=100_000,
    benchmark_options={"SPY": spy_options_df, "QQQ": qqq_options_df},
)
report.plot_summary()  # includes "SPY ATM Call Return" row
```

## Custom Panels

```python
@report.panel("my_chart")
def my_chart(data):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=data.trade_log["exit_type"], y=data.trade_log["realized_pnl"]))
    return fig

report.plot_dashboard()  # now includes your custom panel
```

## Panel Management

```python
report.remove_panel("exit_breakdown")  # remove a default panel
report.add_panel("custom", my_factory)  # add a panel programmatically
report.list_panels()                    # list registered panel keys
```

## Data Access

The `BacktestReport` pre-extracts validated data into a `BacktestData` object, accessible via `report.data`:

```python
report.data.capital            # Initial capital
report.data.has_trades         # Whether trade log has data
report.data.has_equity         # Whether equity curve has data
report.data.trade_log          # DataFrame with all trades
report.data.equity_curve       # Date-indexed Series
report.data.summary            # Dict of 22+ metrics
report.data.leg_results        # Per-leg data keyed by leg name
report.data.stock_prices       # Dict of symbol → close price Series
report.data.benchmark_equity   # Dict of label → benchmark equity curve Series
report.data.benchmark_summaries  # Dict of label → benchmark summary metrics
```

## Legacy API

The old function-based API still works but is deprecated:

```python
from backtest_charts import plot_equity_curve, plot_dashboard
plot_equity_curve(result, 100_000)  # DeprecationWarning
```

## Requirements

- Python ≥ 3.12
- plotly ≥ 5.0
- pandas ≥ 2.0
