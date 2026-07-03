"""Roll / close decision rules for short option positions.

Ported from thetagang's ``options_engine.put_can_be_rolled`` /
``call_can_be_rolled`` / ``position_can_be_closed`` (options_engine.py:776-958), as
pure functions over a position snapshot. The original logic is async only because it
fetches a live ticker to test ITM; here ITM is an input, so the decisions are
deterministic and unit-testable — and reusable by both backtests and research.

Decision order (put and call symmetric):

1. ``always_when_itm`` and ITM            -> roll
2. ``itm == False`` and ITM               -> do NOT roll
3. excess position and ``has_excess`` False -> do NOT roll
4. ``max_dte`` set and ``dte > max_dte``   -> do NOT roll
5. ``dte <= roll_dte`` and ``pnl >= min_pnl`` -> roll (DTE trigger)
6. ``pnl >= pnl``                          -> roll (profit trigger)

A position is closed when ``close_at_pnl`` is set (default 1.0 == 100% of max profit)
and ``pnl > close_at_pnl``.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RollWhenLegConfig:
    """Per-leg (call/put) roll configuration.

    Attributes:
        itm: Whether to roll ITM positions (calls default True, puts default False).
        always_when_itm: If True, force a roll whenever the leg is ITM (overrides ``itm``).
        credit_only: Whether the roll must be for a credit (not modelled in the decision
            itself; used by the order layer).
        has_excess: Whether to roll when the symbol has excess positions (default True).
        maintain_high_water_mark: Calls only — floor the roll strike at the prior short
            strike (handled by the strike-selection layer, not this decision).

    """

    itm: bool = True
    always_when_itm: bool = False
    credit_only: bool = False
    has_excess: bool = True
    maintain_high_water_mark: bool = False


@dataclass(frozen=True)
class RollWhenConfig:
    """Roll / close thresholds, mirroring thetagang's ``RollWhenConfig``.

    Attributes:
        dte: Roll when ``dte <= this`` (DTE trigger), gated by ``min_pnl``.
        pnl: Roll when ``pnl >= this`` (profit trigger), as a fraction of max profit.
        min_pnl: Minimum P&L to satisfy the DTE trigger.
        close_at_pnl: Close when ``pnl > this`` (default 1.0 == 100%).
        close_if_unable_to_roll: Close instead of leaving open when no roll target found.
        max_dte: Optional cap; never roll when ``dte > max_dte``.
        calls: Per-call-leg roll config.
        puts: Per-put-leg roll config.

    """

    dte: int
    pnl: Decimal = Decimal("0.0")
    min_pnl: Decimal = Decimal("0.0")
    close_at_pnl: Decimal = Decimal("1.0")
    close_if_unable_to_roll: bool = False
    max_dte: int | None = None
    calls: RollWhenLegConfig = RollWhenLegConfig(itm=True)
    puts: RollWhenLegConfig = RollWhenLegConfig(itm=False)


@dataclass(frozen=True)
class PositionSnapshot:
    """A short option position reduced to the fields the roll/close rules need.

    Attributes:
        symbol: Underlying symbol.
        right: ``"C"`` for calls, ``"P"`` for puts.
        strike: Strike price.
        spot: Current underlying price (used to derive ITM if not given).
        dte: Days to expiry.
        pnl: Fraction of max profit captured (0.0..1.0+).
        itm: Whether the option is in the money. When ``None`` it is derived from
            ``right``/``strike``/``spot`` (call ITM iff ``strike <= spot``;
            put ITM iff ``strike >= spot``).
        has_excess: Whether the symbol has excess positions of this right.

    """

    symbol: str
    right: str
    strike: Decimal
    spot: Decimal
    dte: int
    pnl: Decimal
    itm: bool | None = None
    has_excess: bool = False

    @property
    def is_itm(self) -> bool:
        """Return whether the option is in the money, deriving it if not given."""
        if self.itm is not None:
            return self.itm
        if self.right.upper() == "C":
            return self.strike <= self.spot
        return self.strike >= self.spot


def _should_roll(
    dte: int,
    pnl: Decimal,
    itm: bool,
    has_excess: bool,
    leg_cfg: RollWhenLegConfig,
    roll_cfg: RollWhenConfig,
) -> bool:
    """Apply the symmetric put/call roll decision tree."""
    if leg_cfg.always_when_itm and itm:
        return True
    if not leg_cfg.itm and itm:
        return False
    if has_excess and not leg_cfg.has_excess:
        return False
    if roll_cfg.max_dte is not None and dte > roll_cfg.max_dte:
        return False
    # DTE trigger: near expiry and profitable enough.
    if dte <= roll_cfg.dte and pnl >= roll_cfg.min_pnl:
        return True
    # Profit trigger: captured enough premium regardless of DTE.
    return pnl >= roll_cfg.pnl


def should_roll(position: PositionSnapshot, config: RollWhenConfig) -> bool:
    """Return whether a short option position should be rolled."""
    leg_cfg = config.calls if position.right.upper() == "C" else config.puts
    return _should_roll(
        position.dte,
        position.pnl,
        position.is_itm,
        position.has_excess,
        leg_cfg,
        config,
    )


def should_close(position: PositionSnapshot, config: RollWhenConfig) -> bool:
    """Return whether a short option position should be closed for profit.

    Triggered when ``close_at_pnl`` is set (truthy) and the position's P&L fraction
    exceeds it (default: close at 100% of max profit).
    """
    if config.close_at_pnl:
        return position.pnl > config.close_at_pnl
    return False


def next_roll_strike_for_call(
    short_strike: Decimal,
    spot: Decimal,
    stock_avg_cost: Decimal | None = None,
    maintain_high_water_mark: bool = False,
    prior_short_strike: Decimal | None = None,
    strike_limit: Decimal | None = None,
) -> Decimal:
    """Return the strike floor for the next short call in a roll.

    Mirrors thetagang ``roll_positions`` (options_engine.py:1122-1135): a covered call's
    roll strike is floored at the stock cost basis (and optionally the prior short
    strike under a high-water-mark policy) so the roll never sells below cost.

    Args:
        short_strike: The current short call's strike.
        spot: Current underlying price.
        stock_avg_cost: Average cost of the underlying shares (the cost-basis floor).
        maintain_high_water_mark: If True, never roll the strike below ``prior_short_strike``.
        prior_short_strike: The strike of the short call being rolled (HWM floor).
        strike_limit: An explicit per-symbol strike limit to honor.

    Returns:
        The effective strike floor for selecting the new short call.

    """
    floor = short_strike
    if stock_avg_cost is not None:
        floor = max(floor, stock_avg_cost)
    if maintain_high_water_mark and prior_short_strike is not None:
        floor = max(floor, prior_short_strike)
    if strike_limit is not None:
        floor = max(floor, strike_limit)
    return floor


def next_roll_strike_for_put(
    short_strike: Decimal,
    spot: Decimal,
    prior_short_strike: Decimal | None = None,
    strike_limit: Decimal | None = None,
) -> Decimal:
    """Return the strike ceiling for the next short put in a roll.

    A short put roll should not lose money: cap the new strike so the credit received
    keeps the roll at-or-below cost. When ITM, also cap at the prior strike so the roll
    does not move further ITM.

    Args:
        short_strike: The current short put's strike.
        spot: Current underlying price.
        prior_short_strike: The strike being rolled; caps the new strike when ITM.
        strike_limit: An explicit per-symbol strike ceiling to honor.

    Returns:
        The effective strike ceiling for selecting the new short put.

    """
    ceiling = short_strike
    if prior_short_strike is not None and short_strike >= spot:
        # ITM roll: do not move the strike further ITM.
        ceiling = min(ceiling, prior_short_strike)
    if strike_limit is not None:
        ceiling = min(ceiling, strike_limit)
    return ceiling
