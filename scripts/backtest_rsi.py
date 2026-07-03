"""Backtest the RSI double-touch strategy on SPY hourly bars.

Loads ``SPY.ARCA-1-HOUR-LAST-EXTERNAL`` from the shared ParquetDataCatalog and runs
:class:`trade_system_strategies.rsi.strategy.RsiStrategy` on a simulated ARCA venue.

Run:
    uv run --all-packages python scripts/backtest_rsi.py
"""

from decimal import Decimal

from nautilus_trader.analysis.tearsheet import create_tearsheet
from nautilus_trader.backtest.config import BacktestDataConfig
from nautilus_trader.backtest.config import BacktestRunConfig
from nautilus_trader.backtest.config import BacktestVenueConfig
from nautilus_trader.backtest.engine import BacktestEngineConfig
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import TraderId


# The catalog lives at the repo root (NAUTILUS_PATH points here; data/ holds the parquet).
CATALOG_PATH = r"E:/TMP/trade-system"
INSTRUMENT_ID = "SPY.ARCA"
BAR_SPEC = "1-HOUR-LAST"
START_TIME = "2026-01-02T00:00:00+00:00"
END_TIME = "2026-06-30T00:00:00+00:00"


def main() -> None:
    """Configure and run the RSI backtest, then print the result summary."""
    venue = BacktestVenueConfig(
        name="ARCA",  # must match the instrument's venue
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        book_type="L1_MBP",
        base_currency="USD",
        starting_balances=["10_000 USD"],
    )

    data = BacktestDataConfig(
        catalog_path=CATALOG_PATH,
        data_cls=Bar,
        instrument_id=INSTRUMENT_ID,
        bar_spec=BAR_SPEC,
        start_time=START_TIME,
        end_time=END_TIME,
    )

    strategy = ImportableStrategyConfig(
        strategy_path="trade_system_strategies.rsi.strategy:RsiStrategy",
        config_path="trade_system_strategies.rsi.config:RsiConfig",
        config={
            "instrument_id": INSTRUMENT_ID,
            "bar_type": f"{INSTRUMENT_ID}-{BAR_SPEC}-EXTERNAL",
            "rsi_period": 14,
            "upper_level": 0.70,
            "lower_level": 0.30,
            "midline": 0.50,
            "trade_size": str(Decimal("100")),
        },
    )

    run_config = BacktestRunConfig(
        engine=BacktestEngineConfig(
            trader_id=TraderId("RSI-BACKTEST-001"),
            strategies=[strategy],
            run_analysis=True,
        ),
        venues=[venue],
        data=[data],
        dispose_on_completion=False,
    )

    node = BacktestNode([run_config])
    results = node.run()

    for result in results:
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

    # Interactive HTML tearsheet from the (still-alive) engine.
    engines = node.get_engines()
    if engines:
        output_path = "rsi_tearsheet.html"
        create_tearsheet(engines[0], output_path=output_path, title="RSI Double-Touch — SPY Hourly")
        print(f"\nTearsheet written to: {output_path}")


if __name__ == "__main__":
    main()
