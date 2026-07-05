"""Matrix backtest the RSI double-touch strategy with a parameter grid.

Uses :func:`~trade_system_core.backtest.grid_backtest` to sweep over
RSI period and band level combinations.

Run:
    uv run --all-packages python scripts/backtest_rsi_grid.py
"""

from decimal import Decimal

from trade_system_core import grid_backtest


def main() -> None:
    """Run the RSI grid backtest and print the top results."""
    results = grid_backtest(
        strategy_path="trade_system_strategies.rsi.strategy:RsiStrategy",
        config_path="trade_system_strategies.rsi.config:RsiConfig",
        base_config={
            "instrument_id": "SPY.ARCX",
            "bar_type": "SPY.ARCX-1-MINUTE-LAST-EXTERNAL",
            "midline": 0.50,
            "trade_size": str(Decimal("100")),
        },
        param_grid={
            "rsi_period": [10, 14, 20],
            "upper_level": [0.65, 0.70, 0.75],
            "lower_level": [0.25, 0.30, 0.35],
        },
        instrument_id="SPY.ARCX",
        bar_type="SPY.ARCX-1-MINUTE-LAST-EXTERNAL",
        catalog_path=".",
        start_time="2026-01-02T00:00:00+00:00",
        end_time="2026-06-30T00:00:00+00:00",
        starting_balances=["10_000 USD"],
    )

    print("\n========== Grid Backtest Results ==========")
    print(f"Total combinations: {len(results)}")
    print("")
    for idx, r in enumerate(results[:10], 1):
        print(f"#{idx}  params={r.params}  PnL={r.total_pnl}  DD={r.max_drawdown}  trades={r.total_trades}")


if __name__ == "__main__":
    main()
