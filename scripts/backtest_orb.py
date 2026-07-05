"""Backtest the Opening Range Breakout (ORB) strategy on SPY 1-minute bars.

Uses the :func:`~trade_system_core.backtest.quick_backtest` shorthand.

Run:
    uv run --all-packages python scripts/backtest_orb.py
"""

from decimal import Decimal

from trade_system_core import quick_backtest


def main() -> None:
    """Run the ORB backtest and print the result summary."""
    result = quick_backtest(
        strategy_path="trade_system_strategies.orb.strategy:OrbStrategy",
        config_path="trade_system_strategies.orb.config:OrbConfig",
        strategy_config={
            "instrument_id": "SPY.ARCX",
            "bar_type": "SPY.ARCX-1-MINUTE-LAST-EXTERNAL",
            "opening_range_minutes": 60,
            "breakout_buffer_pct": 0.001,
            "use_atr_stop": True,
            "atr_period": 14,
            "atr_stop_mult": 2.0,
            "use_time_exit": True,
            "exit_time": "15:45",
            "trade_size": str(Decimal("100")),
        },
        instrument_id="SPY.ARCX",
        bar_type="SPY.ARCX-1-MINUTE-LAST-EXTERNAL",
        catalog_path=".",
        start_time="2026-01-02T00:00:00+00:00",
        end_time="2026-06-30T00:00:00+00:00",
        starting_balances=["100_000 USD"],
        tearsheet=True,
        output_dir=".tmp",
    )

    print("\n========== ORB Backtest Result ==========")
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
