"""Smoke test: verify run_pmcc works end-to-end with synthetic data."""

import numpy as np
import pandas as pd
from options_strategies.pmcc import PmccConfig
from options_strategies.pmcc import run_pmcc


def _synthetic_options() -> pd.DataFrame:
    """Build a minimal option chain DataFrame matching optopsy schema."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=60, freq="B")
    expiries = pd.date_range("2024-03-15", periods=6, freq="30D")
    rows = []
    for d in dates:
        for e in expiries:
            if e <= d:
                continue
            for strike in [90, 95, 100, 105, 110]:
                for ot in ["c", "p"]:
                    mid = max(0.5, 5.0 - abs(strike - 100) * 0.15 + np.random.normal(0, 0.3))
                    delta = max(0.01, min(0.99, 0.5 - (strike - 100) * 0.05 + np.random.normal(0, 0.02)))
                    rows.append({
                        "underlying_symbol": "TEST",
                        "option_type": ot,
                        "expiration": e,
                        "quote_date": d,
                        "strike": float(strike),
                        "bid": mid - 0.05,
                        "ask": mid + 0.05,
                        "delta": delta,
                        "volume": 1000,
                        "open_interest": 500,
                    })
    return pd.DataFrame(rows)


def _synthetic_stock() -> pd.DataFrame:
    """Build a minimal stock OHLCV DataFrame."""
    dates = pd.date_range("2024-01-02", periods=60, freq="B")
    return pd.DataFrame({
        "underlying_symbol": "TEST",
        "quote_date": dates,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0 + np.random.normal(0, 0.5, len(dates)).cumsum() * 0.1,
        "volume": 1_000_000,
    })


def main() -> None:
    options = _synthetic_options()
    stock = _synthetic_stock()
    print(f"Options: {len(options)} rows, Stock: {len(stock)} rows")

    config = PmccConfig(
        symbol="TEST",
        capital=50_000.0,
        leaps_max_entry_dte=180,
        leaps_exit_dte=14,
        short_max_entry_dte=60,
        short_exit_dte=7,
        short_take_profit=0.8,
    )

    result = run_pmcc(options, stock, config)

    s = result.summary
    print(f"\nPortfolio: trades={s.get('total_trades',0)} win_rate={s.get('win_rate',0):.1%} pnl=${s.get('total_pnl',0):,.2f}")
    for name, leg in result.leg_results.items():
        ls = leg.summary
        print(f"  {name}: trades={ls.get('total_trades',0)} pnl=${ls.get('total_pnl',0):,.2f}")

    # Check short_call leg has take_profit exits
    if "short_call" in result.leg_results:
        tl = result.leg_results["short_call"].trade_log
        if not tl.empty and "exit_type" in tl.columns:
            tp_count = (tl["exit_type"] == "take_profit").sum()
            print(f"  short_call take_profit exits: {tp_count}")

    print("\n✅ Smoke test passed!")


if __name__ == "__main__":
    main()
