"""Backtest the RSI double-touch strategy on SPY hourly bars.

Uses the :func:`~trade_system_core.backtest.quick_backtest` shorthand.

Run:
    uv run --all-packages python scripts/backtest_rsi.py
"""

from decimal import Decimal

from trade_system_core import quick_backtest


def main() -> None:
    """Run the RSI backtest and print the result summary."""
    result = quick_backtest(
        strategy_path="trade_system_strategies.rsi.strategy:RsiStrategy",
        config_path="trade_system_strategies.rsi.config:RsiConfig",
        strategy_config={
            "instrument_id": "SPY.ARCA",
            "bar_type": "SPY.ARCA-1-MINUTE-LAST-EXTERNAL",
            "rsi_period": 14,
            "upper_level": 0.70,
            "lower_level": 0.30,
            "midline": 0.50,
            "trade_size": str(Decimal("100")),
        },
        instrument_id="SPY.ARCA",
        bar_type="SPY.ARCA-1-MINUTE-LAST-EXTERNAL",
        catalog_path=".",
        start_time="2026-01-02T00:00:00+00:00",
        end_time="2026-06-30T00:00:00+00:00",
        starting_balances=["10_000 USD"],
        tearsheet=True,
    )

    print("\n========== RSI Backtest Result ==========")
    print(f"run_id:          {result.run_id}")
    print(f"backtest range:  {result.backtest_start} -> {result.backtest_end}")
    print(f"elapsed (s):     {result.elapsed_time:.2f}")
    print(f"total events:    {result.total_events}")
    print(f"total orders:    {result.total_orders}")
    print(f"total positions: {result.total_positions}")

    print("\n--- summary ---")
    for key, value in result.summary.items():
        print(f"{key}: {value}")

    print("\n--- PnL stats ---")
    for currency, stats in result.stats_pnls.items():
        print(f"[{currency}] {stats}")


if __name__ == "__main__":
    main()
