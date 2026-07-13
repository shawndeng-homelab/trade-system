"""PMCC strategy configuration."""

from decimal import Decimal

from nautilus_trader.config import StrategyConfig


class PMCCConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`~trade_system_strategies.pmcc.strategy.PMCCStrategy`.

    PMCC = long a deep-ITM LEAPS call (far expiry, ~0.8 delta) + short a near-term OTM
    call (~0.3 delta), reproducing a covered-call payoff at a fraction of the capital.

    Attributes:
        underlying: The underlying instrument id, e.g. ``"SPY.ARCA"``.
        bar_type: Bar type to subscribe to. When ``None``, auto-constructed from
            ``underlying`` as ``"<underlying>-1-HOUR-LAST-EXTERNAL"``.
        leaps_target_delta: Target absolute delta for the long LEAPS leg.
        leaps_min_dte: Minimum DTE for LEAPS selection (far expiry).
        leaps_max_dte: Optional maximum DTE for LEAPS selection.
        leaps_quantity: Number of LEAPS contracts to buy (each covers 100 shares).
        leaps_roll_when_dte: Roll LEAPS when DTE drops below this threshold.
        leaps_roll_when_delta_below: Roll LEAPS when absolute delta drifts below this.
        short_target_delta: Target absolute delta for the short near-term call leg.
        short_min_dte: Minimum DTE for short call selection (near-term).
        short_max_dte: Optional maximum DTE for short call selection.
        short_quantity: Number of short calls per LEAPS (usually 1).
        short_delta_tolerance: Max acceptable delta gap when selecting the short leg.
        short_roll_dte: Roll the short call when DTE drops below this (DTE trigger).
        short_roll_pnl: Roll the short call when PnL fraction >= this (profit trigger).
        short_roll_min_pnl: Minimum PnL fraction to satisfy the DTE trigger.
        short_close_at_pnl: Close the short call for profit when PnL exceeds this
            (default 0.90 = 90% of max profit).
        short_always_roll_when_itm: Always roll the short call when it is ITM.
        short_credit_only: Short call roll must be for a net credit.
        short_maintain_high_water_mark: Never roll the short call below the prior
            short strike (high-water-mark policy).
        close_positions_on_stop: Close any open positions when the strategy stops.

    """

    underlying: str = "SPY.ARCA"
    bar_type: str | None = None

    leaps_target_delta: Decimal = Decimal("0.80")
    leaps_min_dte: int = 60
    leaps_max_dte: int | None = None
    leaps_quantity: Decimal = Decimal("1")
    leaps_roll_when_dte: int = 90
    leaps_roll_when_delta_below: Decimal = Decimal("0.70")

    short_target_delta: Decimal = Decimal("0.30")
    short_min_dte: int = 7
    short_max_dte: int | None = 45
    short_quantity: Decimal = Decimal("1")
    short_delta_tolerance: Decimal | None = None
    short_roll_dte: int = 7
    short_roll_pnl: Decimal = Decimal("0.50")
    short_roll_min_pnl: Decimal = Decimal("0.25")
    short_close_at_pnl: Decimal = Decimal("0.90")
    short_always_roll_when_itm: bool = True
    short_credit_only: bool = False
    short_maintain_high_water_mark: bool = True

    close_positions_on_stop: bool = True
