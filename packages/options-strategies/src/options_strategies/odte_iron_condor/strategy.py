"""0DTE Iron Condor backtest strategy powered by optopsy.

An iron condor is a 4-leg neutral strategy: long put (wing) + short put
(income) + short call (income) + long call (wing).  The near-expiry variant
enters 1–3 days before expiration and exits at or near expiration (DTE 0),
capturing rapid time decay in the final sessions.

Uses ``optopsy.iron_condor`` as the strategy function with per-leg delta
targeting via ``leg1_delta`` through ``leg4_delta``.  Multiple underlyings
(e.g. SPY, QQQ, IWM) are combined as independent legs in
``optopsy.simulate_portfolio`` with equal capital weighting.
"""

import optopsy as op
from optopsy.types import TargetRange

from options_strategies.odte_iron_condor.config import OdteIronCondorConfig
from options_strategies.odte_iron_condor.signals import odte_entry_dates


def run_odte_iron_condor(
    options_df: dict[str, object],
    stock_df: dict[str, object],
    config: OdteIronCondorConfig,
):
    """Run a 0DTE iron condor backtest via optopsy.

    Each symbol in ``config.symbols`` becomes an independent portfolio leg
    with equal capital weight.  The iron condor's four sub-legs (long put,
    short put, short call, long call) are handled internally by
    ``optopsy.iron_condor``.

    Args:
        options_df: Mapping of symbol → option chain DataFrame.  Each key
            must match an entry in ``config.symbols``.
        stock_df: Mapping of symbol → stock OHLCV DataFrame.
        config: 0DTE iron condor configuration.

    Returns:
        ``optopsy.simulator.PortfolioResult`` with combined trade log,
        equity curve, summary, and per-leg results.
    """
    n_symbols = len(config.symbols)
    weight = 1.0 / n_symbols

    legs = []
    for sym in config.symbols:
        opt_data = options_df[sym]
        stk_data = stock_df[sym]

        entry = odte_entry_dates(stk_data, entry_cycle=config.entry_cycle, entry_time=config.entry_time)

        # ── Per-leg delta targeting ─────────────────────────────────────
        leg1_delta = TargetRange(
            target=config.long_put_delta,
            min=config.long_put_delta_min,
            max=config.long_put_delta_max,
        )
        leg2_delta = TargetRange(
            target=config.short_put_delta,
            min=config.short_put_delta_min,
            max=config.short_put_delta_max,
        )
        leg3_delta = TargetRange(
            target=config.short_call_delta,
            min=config.short_call_delta_min,
            max=config.short_call_delta_max,
        )
        leg4_delta = TargetRange(
            target=config.long_call_delta,
            min=config.long_call_delta_min,
            max=config.long_call_delta_max,
        )

        leg: dict = {
            "data": opt_data,
            "strategy": op.iron_condor,
            "weight": weight,
            "name": f"iron_condor_{sym}",
            "quantity": config.quantity,
            "max_positions": config.max_positions,
            "multiplier": config.multiplier,
            # 4-leg delta targeting
            "leg1_delta": leg1_delta,
            "leg2_delta": leg2_delta,
            "leg3_delta": leg3_delta,
            "leg4_delta": leg4_delta,
            # DTE constraints
            "max_entry_dte": config.max_entry_dte,
            "exit_dte": config.exit_dte,
            "exit_dte_tolerance": config.exit_dte_tolerance,
            # Entry signal
            "entry_dates": entry,
            # Risk management
            "take_profit": config.take_profit,
            "stop_loss": config.stop_loss,
        }

        legs.append(leg)

    # ── Run portfolio simulation ───────────────────────────────────────
    return op.simulate_portfolio(legs, capital=config.capital)
