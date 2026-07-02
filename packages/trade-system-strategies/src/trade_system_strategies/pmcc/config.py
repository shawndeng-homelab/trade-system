"""PMCC strategy configuration."""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig


class PMCCConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`~trade_system_strategies.pmcc.strategy.PMCCStrategy`.

    PMCC = long a deep-ITM LEAPS call (far expiry, ~0.8 delta) + short a near-term OTM
    call (~0.3 delta), reproducing a covered-call payoff at a fraction of the capital.

    Attributes:
        underlying: The underlying instrument id, e.g. ``"SPY.ARCA"``.
        leaps_target_delta: Target absolute delta for the long LEAPS leg.
        short_target_delta: Target absolute delta for the short near-term call leg.
        leaps_quantity: Number of LEAPS contracts to buy (each covers 100 shares).
        short_quantity: Number of short calls per LEAPS (usually 1).
        short_delta_tolerance: Max acceptable delta gap when selecting the short leg.

    """

    underlying: str
    leaps_target_delta: Decimal = Decimal("0.80")
    short_target_delta: Decimal = Decimal("0.30")
    leaps_quantity: Decimal = Decimal("1")
    short_quantity: Decimal = Decimal("1")
    short_delta_tolerance: Decimal | None = None
