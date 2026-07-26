"""Backtest the PMCC (Poor Man's Covered Call) strategy on SPY via optopsy.

Requires pre-downloaded data::

    EODHD_API_KEY=... optopsy-data download SPY        # options
    optopsy-data download SPY -s                       # stock OHLCV

Run::

    uv run --all-packages python scripts/backtest_pmcc.py
"""

from options_strategies.pmcc import PmccConfig
from options_strategies.pmcc import run_pmcc
from options_strategies.shared import load_pmcc_data


def main() -> None:
    """Run the PMCC backtest and print the result summary."""
    config = PmccConfig(
        symbol="SPY",
        capital=100_000.0,
        # LEAPS: deep-ITM, far expiry
        leaps_delta=0.80,
        leaps_max_entry_dte=365,
        leaps_exit_dte=30,
        # Short call: near-term, 80% profit exit
        short_delta=0.30,
        short_max_entry_dte=45,
        short_exit_dte=7,
        short_take_profit=0.8,
    )

    print(f"Loading data for {config.symbol}…")
    options, stock = load_pmcc_data(
        config.symbol,
        start_date=config.start_date,
        end_date=config.end_date,
        expiration_type=config.expiration_type,
    )
    print(f"  Options: {len(options):,} rows")
    print(f"  Stock:   {len(stock):,} rows")

    print("Running PMCC backtest…")
    result = run_pmcc(options, stock, config)

    # ── Summary ────────────────────────────────────────────────────────────
    s = result.summary
    print("\n═══ PMCC Portfolio Summary ═══")
    print(f"  Total trades:    {s.get('total_trades', 0)}")
    print(f"  Win rate:        {s.get('win_rate', 0):.1%}")
    print(f"  Total P&L:       ${s.get('total_pnl', 0):,.2f}")
    print(f"  Max drawdown:    {s.get('max_drawdown', 0):.2%}")
    print(f"  Sharpe ratio:    {s.get('sharpe_ratio', 0):.2f}")
    print(f"  Sortino ratio:   {s.get('sortino_ratio', 0):.2f}")
    print(f"  Profit factor:   {s.get('profit_factor', 0):.2f}")
    print(f"  Avg days held:   {s.get('avg_days_in_trade', 0):.1f}")

    # ── Per-leg results ────────────────────────────────────────────────────
    for name, leg in result.leg_results.items():
        ls = leg.summary
        print(f"\n  ── {name} leg ──")
        print(f"    Trades: {ls.get('total_trades', 0)}  "
              f"Win rate: {ls.get('win_rate', 0):.1%}  "
              f"P&L: ${ls.get('total_pnl', 0):,.2f}")

    # ── Trade log sample ───────────────────────────────────────────────────
    if not result.trade_log.empty:
        print("\n  Sample trades (first 5):")
        print(result.trade_log.head().to_string(index=False))


if __name__ == "__main__":
    main()
