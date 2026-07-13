"""PMCC-specific leg-selection and lifecycle decision logic (pure functions).

Shared between :mod:`~trade_system_strategies.pmcc.strategy` and research notebooks so
the decisions used in a backtest are identical to the ones explored in Jupyter.

Three lifecycle phases drive the PMCC:

1. **Entry** — select LEAPS + short call legs and open the combo.
2. **Short-call management** — roll or close the near-term call when it reaches a
   profit target or nears expiry (delegates to :mod:`~trade_system_strategies.shared.management`).
3. **LEAPS management** — roll the LEAPS when its DTE drops or delta drifts away
   from the stock-substitute range (PMCC-specific, not in thetagang's standard wheel).

All functions operate on plain data (Decimals, ints, lists of tuples) — no
NautilusTrader types, no engine coupling.
"""

from decimal import Decimal
from enum import Enum

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.shared.legs import LegSpec
from trade_system_strategies.shared.management import PositionSnapshot
from trade_system_strategies.shared.management import RollWhenConfig
from trade_system_strategies.shared.management import RollWhenLegConfig
from trade_system_strategies.shared.management import next_roll_strike_for_call
from trade_system_strategies.shared.management import should_close
from trade_system_strategies.shared.management import should_roll
from trade_system_strategies.shared.selection import OptionCandidate
from trade_system_strategies.shared.selection import SelectionConfig
from trade_system_strategies.shared.selection import long_leg_by_delta
from trade_system_strategies.shared.selection import select_short_option
from trade_system_strategies.shared.selection import short_leg_by_delta


class PMCCAction(Enum):
    """Action returned by PMCC lifecycle decision functions."""

    HOLD = 0
    ENTER = 1
    ROLL_SHORT = 2
    CLOSE_SHORT = 3
    ROLL_LEAPS = 4
    EXIT_ALL = 5


def pmcc_entry_decision(
    has_active_position: bool,
    has_pending_orders: bool,
) -> PMCCAction:
    """Determine whether to enter a new PMCC position.

    Returns ``ENTER`` only when flat with no pending orders; ``HOLD`` otherwise.
    The initial implementation supports a single PMCC position per strategy instance.

    Args:
        has_active_position: Whether an active LegGroup is tracked.
        has_pending_orders: Whether any leg orders are still unfilled.

    Returns:
        :class:`PMCCAction` — ``ENTER`` or ``HOLD``.

    """
    if has_active_position or has_pending_orders:
        return PMCCAction.HOLD
    return PMCCAction.ENTER


def pmcc_short_call_decision(
    position_snapshot: PositionSnapshot,
    roll_config: RollWhenConfig,
) -> PMCCAction:
    """Determine whether the short call should be rolled, closed, or held.

    Delegates to :func:`~trade_system_strategies.shared.management.should_roll` and
    :func:`~trade_system_strategies.shared.management.should_close` — the same
    decision tree thetagang uses for covered-call management.

    Args:
        position_snapshot: The short call position reduced to the fields the
            roll/close rules need (strike, DTE, PnL, ITM, excess).
        roll_config: Roll / close thresholds from :func:`pmcc_roll_config_from_pmcc_config`.

    Returns:
        :class:`PMCCAction` — ``ROLL_SHORT``, ``CLOSE_SHORT``, or ``HOLD``.

    """
    if should_close(position_snapshot, roll_config):
        return PMCCAction.CLOSE_SHORT
    if should_roll(position_snapshot, roll_config):
        return PMCCAction.ROLL_SHORT
    return PMCCAction.HOLD


def pmcc_leaps_decision(
    dte: int,
    delta: Decimal,
    leaps_roll_when_dte: int,
    leaps_roll_when_delta_below: Decimal,
) -> PMCCAction:
    """Determine whether the LEAPS should be rolled.

    A LEAPS (long deep-ITM call) is rolled when:
    - DTE drops below ``leaps_roll_when_dte`` (time-decay erosion)
    - Absolute delta drifts below ``leaps_roll_when_delta_below`` (lost stock-substitute
      character — the LEAPS is no longer deep-ITM enough)

    This is a PMCC-specific concern: a standard covered call's stock delta is always
    1.0, but the LEAPS delta drifts with the underlying.

    Args:
        dte: Days to expiry of the current LEAPS position.
        delta: Absolute delta of the current LEAPS position.
        leaps_roll_when_dte: DTE threshold for a LEAPS roll.
        leaps_roll_when_delta_below: Delta floor for a LEAPS roll.

    Returns:
        :class:`PMCCAction` — ``ROLL_LEAPS`` or ``HOLD``.

    """
    if dte <= leaps_roll_when_dte:
        return PMCCAction.ROLL_LEAPS
    if delta < leaps_roll_when_delta_below:
        return PMCCAction.ROLL_LEAPS
    return PMCCAction.HOLD


def select_short_call_roll_target(
    candidates: list[OptionCandidate],
    spot: Decimal,
    prior_short_strike: Decimal,
    leaps_strike: Decimal,
    config: PMCCConfig,
) -> OptionCandidate | None:
    """Select the target short call for a roll.

    Applies :func:`~trade_system_strategies.shared.management.next_roll_strike_for_call`
    to compute the strike floor (using the LEAPS strike as the cost-basis proxy), then
    filters candidates via :func:`~trade_system_strategies.shared.selection.select_short_option`.

    Args:
        candidates: Near-term call candidates from the option chain.
        spot: Current underlying price.
        prior_short_strike: Strike of the short call being rolled (for HWM).
        leaps_strike: Strike of the LEAPS leg (used as cost-basis floor).
        config: PMCC strategy config with roll / DTE / delta parameters.

    Returns:
        The chosen candidate, or ``None`` if no eligible contract exists.

    """
    strike_floor = next_roll_strike_for_call(
        short_strike=prior_short_strike,
        spot=spot,
        stock_avg_cost=leaps_strike,
        maintain_high_water_mark=config.short_maintain_high_water_mark,
        prior_short_strike=prior_short_strike,
    )

    selection_cfg = SelectionConfig(
        right="C",
        target_dte=config.short_min_dte,
        target_delta=config.short_target_delta,
        max_dte=config.short_max_dte,
        minimum_open_interest=0,
        minimum_price=Decimal("0"),
        strike_limit=strike_floor,
        spot=spot,
        exclude_min_dte=config.short_min_dte,
    )
    return select_short_option(candidates, selection_cfg)


def select_leaps_roll_target(
    candidates: list[OptionCandidate],
    spot: Decimal,
    config: PMCCConfig,
) -> OptionCandidate | None:
    """Select the target LEAPS contract for a roll.

    Uses :func:`~trade_system_strategies.shared.selection.select_short_option` with
    ``delta_mode="near"`` so the selected LEAPS has a delta close to
    ``leaps_target_delta`` rather than below it.

    Args:
        candidates: Far-expiry call candidates from the option chain.
        spot: Current underlying price.
        config: PMCC strategy config with LEAPS parameters.

    Returns:
        The chosen candidate, or ``None`` if no eligible contract exists.

    """
    selection_cfg = SelectionConfig(
        right="C",
        target_dte=config.leaps_min_dte,
        target_delta=config.leaps_target_delta,
        max_dte=config.leaps_max_dte,
        minimum_open_interest=0,
        minimum_price=Decimal("0"),
        spot=spot,
        delta_mode="near",
        delta_tolerance=config.leaps_quantity,  # allow some tolerance around target
    )
    return select_short_option(candidates, selection_cfg)


def pmcc_roll_config_from_pmcc_config(config: PMCCConfig) -> RollWhenConfig:
    """Build a :class:`~trade_system_strategies.shared.management.RollWhenConfig` from a PMCC config.

    Maps the short-call roll parameters into the same structure thetagang uses for
    covered-call management, so :func:`pmcc_short_call_decision` can delegate directly
    to :func:`~trade_system_strategies.shared.management.should_roll` /
    :func:`~trade_system_strategies.shared.management.should_close`.

    Args:
        config: The PMCC strategy configuration.

    Returns:
        A :class:`RollWhenConfig` ready for use in roll/close decision functions.

    """
    return RollWhenConfig(
        dte=config.short_roll_dte,
        pnl=config.short_roll_pnl,
        min_pnl=config.short_roll_min_pnl,
        close_at_pnl=config.short_close_at_pnl,
        calls=RollWhenLegConfig(
            itm=True,
            always_when_itm=config.short_always_roll_when_itm,
            credit_only=config.short_credit_only,
            maintain_high_water_mark=config.short_maintain_high_water_mark,
        ),
    )


def select_pmcc_legs(
    config: PMCCConfig,
    leaps_candidates: list[tuple[Decimal, Decimal]],
    short_candidates: list[tuple[Decimal, Decimal]],
    leaps_instrument_id: str,
    short_instrument_id: str,
) -> tuple[LegSpec | None, LegSpec | None]:
    """Select the long LEAPS leg and the short near-term call leg for a PMCC.

    Args:
        config: The PMCC strategy config (target deltas, quantities, tolerance).
        leaps_candidates: ``(strike, delta)`` pairs from the far-expiry chain.
        short_candidates: ``(strike, delta)`` pairs from the near-term chain.
        leaps_instrument_id: Instrument id of the chosen LEAPS contract.
        short_instrument_id: Instrument id of the chosen short call.

    Returns:
        ``(leaps_leg, short_leg)``; either may be ``None`` if no candidate matched.

    """
    leaps_leg = long_leg_by_delta(
        leaps_instrument_id,
        leaps_candidates,
        config.leaps_target_delta,
        config.leaps_quantity,
    )
    short_leg = short_leg_by_delta(
        short_instrument_id,
        short_candidates,
        config.short_target_delta,
        config.short_quantity,
        config.short_delta_tolerance,
    )
    return leaps_leg, short_leg
