"""Backtest the PMCC (Poor Man's Covered Call) strategy on SPY.

Uses the :func:`~trade_system_core.backtest.quick_backtest` shorthand.

Run:
    uv run --all-packages python scripts/backtest_pmcc.py
"""

from decimal import Decimal

from trade_system_core import quick_backtest
from trade_system_core.config import DataConfig


def main() -> None:
    """Run the PMCC backtest and print the result summary."""
    result = quick_backtest(
        strategy_path="trade_system_strategies.pmcc.strategy:PMCCStrategy",
        config_path="trade_system_strategies.pmcc.config:PMCCConfig",
        strategy_config={
            "underlying": "SPY.ARCX",
            "bar_type": "SPY.ARCX-1-HOUR-LAST-EXTERNAL",
            "leaps_target_delta": str(Decimal("0.80")),
            "leaps_min_dte": 60,
            "leaps_max_dte": None,
            "leaps_quantity": str(Decimal("1")),
            "leaps_roll_when_dte": 90,
            "leaps_roll_when_delta_below": str(Decimal("0.70")),
            "short_target_delta": str(Decimal("0.30")),
            "short_min_dte": 7,
            "short_max_dte": 45,
            "short_quantity": str(Decimal("1")),
            "short_delta_tolerance": None,
            "short_roll_dte": 7,
            "short_roll_pnl": str(Decimal("0.50")),
            "short_roll_min_pnl": str(Decimal("0.25")),
            "short_close_at_pnl": str(Decimal("0.90")),
            "short_always_roll_when_itm": True,
            "short_credit_only": False,
            "short_maintain_high_water_mark": True,
            "close_positions_on_stop": True,
        },
        instrument_id="SPY.ARCX",
        bar_type="SPY.ARCX-1-HOUR-LAST-EXTERNAL",
        catalog_path=".",
        start_time="2026-01-02T00:00:00+00:00",
        end_time="2026-06-30T00:00:00+00:00",
        starting_balances=["100_000 USD"],
        tearsheet=True,
        output_dir=".tmp",
        extra_data=[
            DataConfig(
                catalog_path=".",
                data_cls="OptionContract",
                start_time="2026-01-02T00:00:00+00:00",
                end_time="2026-06-30T00:00:00+00:00",
            ),
        ],
    )

    print("\n========== PMCC Backtest Result ==========")
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
