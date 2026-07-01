"""IBKR commission schedules for tiered and fixed pricing across asset classes.

Unlike crypto maker/taker percentages, IBKR commissions are structured per share /
per contract, with a per-order minimum and (for stocks) a cap expressed as a percentage
of trade value. Rules differ per asset class and per pricing plan (Tiered vs Fixed).

The numbers below are the **standard published US retail rates** (US stocks/ETFs and
US equity/index options) as a starting point. They are deliberately kept as plain data
so they are easy to audit and adjust to your own account tier/region. Verify against:

- Stocks/ETFs:  https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- Options:      https://www.interactivebrokers.com/en/pricing/commissions-options.php

Not modelled in v1 (documented so it is a conscious omission): the small variable
exchange / clearing / regulatory pass-through fees IBKR adds on top. Add them later if
you need cent-accurate commissions.
"""

from __future__ import annotations

from decimal import Decimal


# Pricing plan identifiers used by ``IBKRFeeModelConfig.pricing``.
TIERED = "tiered"
FIXED = "fixed"

# Asset class identifiers used to route to the correct schedule.
STOCK = "stock"
FUTURE = "future"
OPTION = "option"
FOREX = "forex"


# --- US stocks / ETFs -----------------------------------------------------------------
# per_share:     commission per share
# min_per_order: minimum commission charged once per order
# max_pct:       cap as a fraction of trade value (notional), applied per fill
STOCK_RULES: dict[str, dict[str, Decimal]] = {
    TIERED: {
        "per_share": Decimal("0.0035"),
        "min_per_order": Decimal("0.35"),
        "max_pct": Decimal("0.01"),
    },
    FIXED: {
        "per_share": Decimal("0.005"),
        "min_per_order": Decimal("1.00"),
        "max_pct": Decimal("0.01"),
    },
}


# --- US options -----------------------------------------------------------------------
# Fixed pricing is a flat per-contract rate; Tiered pricing is premium-based.
OPTION_FIXED: dict[str, Decimal] = {
    "per_contract": Decimal("0.65"),
    "min_per_order": Decimal("1.00"),
}

OPTION_TIERED_MIN_PER_ORDER = Decimal("1.00")

# Premium-based per-contract tiers, evaluated top-down: the first tier whose
# ``premium_gte`` threshold the option premium reaches sets the per-contract rate.
OPTION_TIERED_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.10"), Decimal("0.65")),  # premium >= 0.10  -> 0.65 / contract
    (Decimal("0.05"), Decimal("0.50")),  # 0.05 <= premium  -> 0.50 / contract
    (Decimal("0.00"), Decimal("0.25")),  # premium <  0.05  -> 0.25 / contract
)


def option_tiered_per_contract(premium: Decimal) -> Decimal:
    """Return the tiered per-contract options rate for a given option premium.

    Args:
        premium: The option premium (fill price) as a decimal.

    Returns:
        The per-contract commission rate.

    """
    for premium_gte, rate in OPTION_TIERED_BANDS:
        if premium >= premium_gte:
            return rate
    return OPTION_TIERED_BANDS[-1][1]
