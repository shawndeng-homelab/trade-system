"""Earnings-overnight strategy dispatch.

Wires the signal functions into a two-leg ``optopsy.simulate_portfolio``
run. The legs are pre-filtered by ``select_options_for_events`` so each
leg only ever sees one row per (symbol, date) — optopsy's
``leg1_delta`` becomes a defensive no-op (a wide ``TargetRange(0.5,
0.01, 0.99)`` accepts any delta) and the actual strike selection is
done by our custom logic.

Three position shapes are supported via ``config.structure``:
``"single"`` (one directional leg), ``"strangle"`` (both 2 % OTM legs),
and ``"straddle"`` (both ATM legs). See ``config.py`` for the
trade-offs.

Known limitations (see CLAUDE.md and the strategy docstring):

- The "3:30 PM entry" is approximated by the **T-1 daily high** (the
  closest EOD proxy for the late-session price). For SPY/QQQ the
  3:00–4:00 PM range is typically < 0.1 %, so high is a tight proxy;
  for names with volatile closes the proxy can overstate the reference
  and the strike ends up further OTM than intended.
- The "T open exit" is approximated by the **T EOD** snapshot. The
  intraday move from open to close is not captured.
- The ``$1000`` cost cap is enforced by dropping events whose top
  candidate (or combined two-leg debit) exceeds the cap — no entry, no
  quantity rescaling, no fallback to a cheaper structure.
"""

import optopsy as op
import pandas as pd
from optopsy.types import TargetRange

from options_strategies.earnings_overnight.config import EarningsOvernightConfig
from options_strategies.earnings_overnight.signals import earnings_event_dates
from options_strategies.earnings_overnight.signals import select_options_for_events
from options_strategies.earnings_overnight.signals import split_options_by_side


# A wide delta range that accepts any delta. With exactly one row per
# (symbol, date) in the pre-filtered options_df, optopsy's delta
# targeting is forced to match that single row; this TargetRange is
# only a safety net in case a future change introduces multiple rows.
# TargetRange requires min > 0, so we use 0.01 / 0.99.
_NOOP_DELTA = TargetRange(target=0.5, min=0.01, max=0.99)


def run_earnings_overnight(
    options_df: pd.DataFrame,
    stock_df: pd.DataFrame,
    earnings_calendar: dict[str, list[pd.Timestamp]],
    config: EarningsOvernightConfig,
):
    """Run an earnings-overnight backtest via optopsy.

    Pipeline:

    1. Map each earnings report date to its T-1 (entry) and T (exit)
       trading day, given the stock's trading calendar.
    2. Pre-select the option(s) per event according to
       ``config.structure``:

       - ``"single"`` — the 2 % OTM call **or** put, whichever has the
         higher OI × Volume (a directional bet on the side institutions
         are crowding into).
       - ``"strangle"`` — **both** 2 % OTM legs (非方向性; profits on a
         large move either way, costs ~2× a single leg).
       - ``"straddle"`` — **both** ATM legs (highest premium and gamma;
         frequently busts ``cost_cap_usd``).

       All variants filter by ``min_oi``, ``min_volume``,
       ``max_entry_dte``, and ``cost_cap_usd`` (the cap applies to the
       combined debit for two-leg structures).
    3. Split the pre-selected rows into per-side filtered options_dfs.
    4. Dispatch each non-empty side to ``optopsy.simulate_portfolio``
       as a separate leg. The leg's ``entry_dates`` is the unique
       ``(symbol, quote_date)`` pairs in that side's filtered df; its
       ``leg1_delta`` is a wide no-op range.

    Args:
        options_df: Options chain DataFrame from
            ``optopsy.data.load_cached_options`` (or a synthetic copy).
            Must contain the columns optopsy's ``long_calls`` /
            ``long_puts`` require: ``underlying_symbol, option_type,
            expiration, quote_date, strike, bid, ask, delta``.
        stock_df: Stock OHLCV DataFrame from
            ``optopsy.data.load_cached_stocks`` (or synthetic). Used for
            the T-1 reference price.
        earnings_calendar: Mapping from vendor-native symbol codes to
            sorted lists of report dates. See ``load_earnings_calendar``.
        config: Strategy parameters.

    Returns:
        ``optopsy.simulator.PortfolioResult`` with combined trade log,
        equity curve, summary, and per-leg results.

    Raises:
        ValueError: If no event survives the strike / liquidity filters.
    """
    events = earnings_event_dates(stock_df, earnings_calendar, config)
    selected = select_options_for_events(options_df, stock_df, events, config)
    calls_df, puts_df = split_options_by_side(selected)

    if calls_df.empty and puts_df.empty:
        if not earnings_calendar:
            # No earnings data at all — most likely the cache is empty
            # for the requested symbol(s).
            msg = (
                "Empty earnings calendar. Populate the cache with:\n"
                "    just download-earnings --symbols <SYMBOLS>\n"
                "and ensure the symbols match the ones in your options cache."
            )
        else:
            msg = (
                "No earnings events survived strike/liquidity filters. "
                "Loosen min_oi / min_volume / cost_cap_usd, or check that the "
                "earnings dates fall within your options_df date range."
            )
        raise ValueError(msg)

    # Re-filter the FULL options_df to keep all price rows for the pre-selected
    # options (entry, exit, and any in-between quotes). optopsy's exit logic
    # needs the next quote_date's row to find the exit price; passing only the
    # entry rows would make the simulation unable to close the position.
    def _expand_to_full_history(leg_options: pd.DataFrame) -> pd.DataFrame:
        keys = leg_options[["underlying_symbol", "option_type", "expiration", "strike"]].drop_duplicates()
        merged = keys.merge(
            options_df,
            on=["underlying_symbol", "option_type", "expiration", "strike"],
            how="left",
        )
        return merged

    calls_full = _expand_to_full_history(calls_df) if not calls_df.empty else calls_df
    puts_full = _expand_to_full_history(puts_df) if not puts_df.empty else puts_df

    legs: list[dict] = []
    common_leg_kwargs: dict = {
        "quantity": config.quantity,
        "multiplier": config.multiplier,
        "max_positions": config.max_positions,
        "max_entry_dte": config.max_entry_dte,
        # ``exit_dte=1`` (not 0) because EODHD's daily feed routinely omits
        # the DTE=0 (expiration-day) row. With ``exit_dte=0`` optopsy can't
        # find an exit row and silently drops every trade. Exiting at DTE=1
        # is also the closer match to this strategy's intent: hold overnight
        # through the announcement, then close — not hold to expiry.
        "exit_dte": config.exit_dte,
        "exit_dte_tolerance": config.exit_dte_tolerance,
        "leg1_delta": _NOOP_DELTA,
    }

    if not calls_df.empty:
        call_entry = calls_df[["underlying_symbol", "quote_date"]].drop_duplicates()
        legs.append(
            {
                "data": calls_full,
                "strategy": op.long_calls,
                "weight": config.call_weight if not puts_df.empty else 1.0,
                "name": "earnings_call",
                "entry_dates": call_entry,
                **common_leg_kwargs,
            }
        )
    if not puts_df.empty:
        put_entry = puts_df[["underlying_symbol", "quote_date"]].drop_duplicates()
        legs.append(
            {
                "data": puts_full,
                "strategy": op.long_puts,
                "weight": config.put_weight if not calls_df.empty else 1.0,
                "name": "earnings_put",
                "entry_dates": put_entry,
                **common_leg_kwargs,
            }
        )

    return op.simulate_portfolio(legs, capital=config.capital)
