"""Backtest the Opening Range Breakout (ORB) strategy on SPY 1-minute bars.

Uses NautilusTrader's BacktestEngine directly.

Run:
    uv run --all-packages python scripts/backtest_orb.py
"""

import os
from decimal import Decimal

from nautilus_trader.backtest.config import BacktestDataConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.engine import BacktestEngineConfig
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog


def main() -> None:
    """Run the ORB backtest and print the result summary."""
    catalog_path = os.environ.get("NAUTILUS_PATH", ".")
    catalog = ParquetDataCatalog(catalog_path)

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("ORB-BT-001"),
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="trade_system_strategies.orb.strategy:OrbStrategy",
                    config_path="trade_system_strategies.orb.config:OrbConfig",
                    config={
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
                ),
            ],
            run_analysis=True,
        ),
    )

    engine.add_venue(
        venue=Venue("ARCX"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money.from_str("100_000 USD")],
    )

    # Load instruments from catalog
    for instrument in catalog.instruments(instrument_ids=["SPY.ARCX"]):
        engine.add_instrument(instrument)

    # Load bar data
    bar_config = BacktestDataConfig(
        catalog_path=catalog_path,
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id="SPY.ARCX",
        bar_spec="1-MINUTE",
        start_time="2026-01-02T00:00:00+00:00",
        end_time="2026-06-30T00:00:00+00:00",
    )
    result = BacktestNode.load_data_config(bar_config)
    if result.data:
        engine.add_data(result.data, sort=False)

    engine.sort_data()
    engine.run(start="2026-01-02T00:00:00+00:00", end="2026-06-30T00:00:00+00:00")

    bt = engine.get_result()
    print("\n========== ORB Backtest Result ==========")
    print(f"run_id:          {bt.run_id}")
    print(f"backtest range:  {bt.backtest_start} -> {bt.backtest_end}")
    print(f"elapsed (s):     {bt.elapsed_time:.2f}")
    print(f"total events:    {bt.total_events}")
    print(f"total orders:    {bt.total_orders}")
    print(f"total positions: {bt.total_positions}")

    print("\n--- summary ---")
    for key, value in bt.summary.items():
        print(f"{key}: {value}")

    print("\n--- PnL stats ---")
    for currency, stats in bt.stats_pnls.items():
        print(f"[{currency}] {stats}")


if __name__ == "__main__":
    main()
