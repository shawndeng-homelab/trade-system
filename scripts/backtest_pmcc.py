"""Backtest the PMCC (Poor Man's Covered Call) strategy on SPY.

Uses NautilusTrader's BacktestEngine directly (the recommended API for
full control over venue registration, instrument loading, and data
streaming).

Run:
    uv run --all-packages python scripts/backtest_pmcc.py
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


# ── Configuration ────────────────────────────────────────────────────────

START_TIME = "2026-01-02T00:00:00+00:00"
END_TIME = "2026-06-30T00:00:00+00:00"

STRATEGY_CONFIG = {
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
}


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the PMCC backtest and print the result summary."""
    catalog_path = os.environ.get("NAUTILUS_PATH", ".")
    catalog = ParquetDataCatalog(catalog_path)

    # ── 1. Engine ─────────────────────────────────────────────────────
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("PMCC-BT-001"),
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="trade_system_strategies.pmcc.strategy:PMCCStrategy",
                    config_path="trade_system_strategies.pmcc.config:PMCCConfig",
                    config=STRATEGY_CONFIG,
                ),
            ],
            run_analysis=True,
        ),
    )

    # ── 2. Venues ─────────────────────────────────────────────────────
    # ARCX: 主交易 venue (SPY equity)
    engine.add_venue(
        venue=Venue("ARCX"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money.from_str("100_000 USD")],
    )
    # OPRA: 期权 venue (US equity options)
    engine.add_venue(
        venue=Venue("OPRA"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money.from_str("0 USD")],
    )
    # XCME: 期货 venue (if catalog contains futures instruments)
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money.from_str("0 USD")],
    )

    # ── 3. Instruments ────────────────────────────────────────────────
    # Load all instruments from the catalog; add_instrument() handles
    # Equity, OptionContract, and FuturesContract uniformly.
    for instrument in catalog.instruments():
        engine.add_instrument(instrument)

    # ── 4. Bar data ──────────────────────────────────────────────────
    bar_config = BacktestDataConfig(
        catalog_path=catalog_path,
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id="SPY.ARCX",
        bar_spec="1-HOUR",
        start_time=START_TIME,
        end_time=END_TIME,
    )
    result = BacktestNode.load_data_config(bar_config)
    if result.data:
        engine.add_data(result.data, sort=False)

    # ── 5. Run ────────────────────────────────────────────────────────
    engine.sort_data()
    engine.run(start=START_TIME, end=END_TIME)

    # ── 6. Result ─────────────────────────────────────────────────────
    bt = engine.get_result()
    print("\n========== PMCC Backtest Result ==========")
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
