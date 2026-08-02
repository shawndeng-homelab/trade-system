"""Smoke test: verify run_odte_iron_condor works end-to-end with synthetic data."""

import numpy as np
import pandas as pd
from options_strategies.odte_iron_condor import OdteIronCondorConfig
from options_strategies.odte_iron_condor import run_odte_iron_condor


def _synthetic_options(symbol: str = "TEST") -> pd.DataFrame:
    """Build a minimal option chain DataFrame matching optopsy schema.

    Includes 0DTE and near-DTE expirations so iron_condor with
    max_entry_dte=1 can find valid contracts.
    """
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=60, freq="B")
    rows = []
    for d in dates:
        # 0DTE: expiration = quote_date
        for dte_offset in [0, 1, 7, 30]:
            e = d + pd.Timedelta(days=dte_offset)
            for strike in [90, 95, 100, 105, 110]:
                for ot in ["c", "p"]:
                    mid = max(0.5, 5.0 - abs(strike - 100) * 0.15 + np.random.normal(0, 0.3))
                    # Puts: delta decreases as strike goes down (OTM put = low delta)
                    # Calls: delta decreases as strike goes up (OTM call = low delta)
                    if ot == "p":
                        delta = max(0.01, min(0.99, 0.5 + (strike - 100) * 0.05 + np.random.normal(0, 0.02)))
                    else:
                        delta = max(0.01, min(0.99, 0.5 - (strike - 100) * 0.05 + np.random.normal(0, 0.02)))
                    rows.append(
                        {
                            "underlying_symbol": symbol,
                            "option_type": ot,
                            "expiration": e,
                            "quote_date": d,
                            "strike": float(strike),
                            "bid": mid - 0.05,
                            "ask": mid + 0.05,
                            "delta": delta,
                            "volume": 1000,
                            "open_interest": 500,
                        }
                    )
    return pd.DataFrame(rows)


def _synthetic_stock(symbol: str = "TEST") -> pd.DataFrame:
    """Build a minimal stock OHLCV DataFrame."""
    dates = pd.date_range("2024-01-02", periods=60, freq="B")
    return pd.DataFrame(
        {
            "underlying_symbol": symbol,
            "quote_date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0 + np.random.normal(0, 0.5, len(dates)).cumsum() * 0.1,
            "volume": 1_000_000,
        }
    )


def main() -> None:
    options = _synthetic_options()
    stock = _synthetic_stock()
    print(f"Options: {len(options)} rows, Stock: {len(stock)} rows")

    config = OdteIronCondorConfig(
        symbol="TEST",
        capital=50_000.0,
        symbols=["TEST"],
        max_entry_dte=1,
        exit_dte=0,
        take_profit=0.5,
        stop_loss=-2.0,
    )

    result = run_odte_iron_condor(
        options_df={"TEST": options},
        stock_df={"TEST": stock},
        config=config,
    )

    s = result.summary
    print(
        f"\nPortfolio: trades={s.get('total_trades', 0)} "
        f"win_rate={s.get('win_rate', 0):.1%} "
        f"pnl=${s.get('total_pnl', 0):,.2f}"
    )
    for name, leg in result.leg_results.items():
        ls = leg.summary
        print(f"  {name}: trades={ls.get('total_trades', 0)} pnl=${ls.get('total_pnl', 0):,.2f}")

    # Check for take_profit and stop_loss exits
    for name, leg in result.leg_results.items():
        tl = leg.trade_log
        if not tl.empty and "exit_type" in tl.columns:
            tp_count = (tl["exit_type"] == "take_profit").sum()
            sl_count = (tl["exit_type"] == "stop_loss").sum()
            print(f"  {name} take_profit exits: {tp_count}, stop_loss exits: {sl_count}")

    print("\n✅ Smoke test passed!")


if __name__ == "__main__":
    main()
