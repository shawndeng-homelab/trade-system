"""PMCC backtest strategy powered by optopsy.

Long LEAPS (deep-ITM, far expiry) + short near-term OTM call, run as
two independent legs via ``optopsy.simulate_portfolio``.  The short call
leg uses ``take_profit`` for 80%-profit early exit; both legs use
independent ``entry_dates`` signals.
"""

import optopsy as op
from optopsy.types import TargetRange

from options_strategies.pmcc.config import PmccConfig
from options_strategies.pmcc.signals import leaps_entry_dates
from options_strategies.pmcc.signals import short_call_entry_dates


def run_pmcc(
    options_df,
    stock_df,
    config: PmccConfig,
):
    """Run a PMCC backtest via optopsy.

    Args:
        options_df: Option chain DataFrame from ``load_cached_options``.
        stock_df: Stock OHLCV DataFrame from ``load_cached_stocks``.
        config: PMCC configuration.

    Returns:
        ``optopsy.simulator.PortfolioResult`` with combined trade log,
        equity curve, summary, and per-leg results.
    """
    # ── Compute independent entry dates ────────────────────────────────────
    leaps_entry = leaps_entry_dates(stock_df)
    short_entry = short_call_entry_dates(stock_df)

    # ── LEAPS leg ──────────────────────────────────────────────────────────
    leaps_delta = TargetRange(
        target=config.leaps_delta,
        min=config.leaps_delta_min,
        max=config.leaps_delta_max,
    )

    leaps_leg: dict = {
        "data": options_df,
        "strategy": op.long_calls,
        "weight": config.leaps_weight,
        "name": "leaps",
        "quantity": config.quantity,
        "max_positions": config.max_positions,
        "multiplier": config.multiplier,
        # Strategy kwargs
        "leg1_delta": leaps_delta,
        "max_entry_dte": config.leaps_max_entry_dte,
        "exit_dte": config.leaps_exit_dte,
        "entry_dates": leaps_entry,
    }
    if config.leaps_max_hold_days is not None:
        leaps_leg["max_hold_days"] = config.leaps_max_hold_days

    # ── Short call leg ─────────────────────────────────────────────────────
    short_delta = TargetRange(
        target=config.short_delta,
        min=config.short_delta_min,
        max=config.short_delta_max,
    )

    short_leg: dict = {
        "data": options_df,
        "strategy": op.short_calls,
        "weight": config.short_weight,
        "name": "short_call",
        "quantity": config.quantity,
        "max_positions": config.max_positions,
        "multiplier": config.multiplier,
        # Strategy kwargs
        "leg1_delta": short_delta,
        "max_entry_dte": config.short_max_entry_dte,
        "exit_dte": config.short_exit_dte,
        "entry_dates": short_entry,
        "take_profit": config.short_take_profit,
    }
    if config.short_max_hold_days is not None:
        short_leg["max_hold_days"] = config.short_max_hold_days

    # ── Run portfolio simulation ───────────────────────────────────────────
    return op.simulate_portfolio(
        [leaps_leg, short_leg],
        capital=config.capital,
    )
