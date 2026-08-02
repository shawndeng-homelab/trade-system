"""Rolling ATM call benchmark strategy powered by optopsy.

Buy ATM call, hold until DTE drops to 150, close and immediately buy
the next ATM call.  Repeat until the backtest end date.  Each symbol
(SPY, QQQ, IWM) runs as an independent leg in ``simulate_portfolio``
with equal capital weighting.

The rolling behavior is achieved by providing every trading day as
``entry_dates`` combined with ``max_positions=1``: optopsy enters on
the first available date, exits when DTE hits ``exit_dte``, and
re-enters on the next trading day automatically.
"""

import optopsy as op
from optopsy.types import TargetRange

from options_strategies.benchmark.config import BenchmarkConfig
from options_strategies.benchmark.signals import benchmark_entry_dates


def run_benchmark(
    options_df: dict[str, object],
    stock_df: dict[str, object],
    config: BenchmarkConfig,
):
    """Run a rolling ATM call benchmark via optopsy.

    Each symbol in ``config.symbols`` becomes an independent portfolio leg
    with equal capital weight.  The ``op.long_calls`` strategy with
    ``exit_dte=150`` and all-trading-day entry dates produces continuous
    rolling ATM call exposure.

    Args:
        options_df: Mapping of symbol → option chain DataFrame.
        stock_df: Mapping of symbol → stock OHLCV DataFrame.
        config: Benchmark configuration.

    Returns:
        ``optopsy.simulator.PortfolioResult`` with combined trade log,
        equity curve, summary, and per-leg results.
    """
    n_symbols = len(config.symbols)
    weight = 1.0 / n_symbols

    delta_range = TargetRange(
        target=config.delta_target,
        min=config.delta_min,
        max=config.delta_max,
    )

    legs = []
    for sym in config.symbols:
        opt_data = options_df[sym]
        stk_data = stock_df[sym]

        entry = benchmark_entry_dates(stk_data)

        leg: dict = {
            "data": opt_data,
            "strategy": op.long_calls,
            "weight": weight,
            "name": f"atm_call_{sym}",
            "quantity": config.quantity,
            "max_positions": config.max_positions,
            "multiplier": config.multiplier,
            # Strategy kwargs
            "leg1_delta": delta_range,
            "max_entry_dte": config.max_entry_dte,
            "exit_dte": config.exit_dte,
            "entry_dates": entry,
        }
        legs.append(leg)

    return op.simulate_portfolio(legs, capital=config.capital)
