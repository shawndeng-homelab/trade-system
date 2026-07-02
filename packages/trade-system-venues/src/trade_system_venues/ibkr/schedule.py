"""IBKR commission schedules for tiered and fixed pricing across asset classes.

Unlike crypto maker/taker percentages, IBKR commissions are structured per share /
per contract, with a per-order minimum and (for stocks) a cap expressed as a percentage
of trade value. Rules differ per asset class and per pricing plan (Tiered vs Fixed).

The numbers below are the **standard published US retail rates** (US stocks/ETFs and
US equity/index options) as a starting point. They are deliberately kept as plain data
so they are easy to audit and adjust to your own account tier/region. Verify against:

- Stocks/ETFs:  https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- Options:      https://www.interactivebrokers.com/en/pricing/commissions-options.php

Tiered stock pricing is **monthly-volume tiered**: the per-share rate drops as the
account's cumulative monthly share volume crosses the published breakpoints (see
``STOCK_TIERED_BANDS``). Fixed pricing is a flat per-share rate regardless of volume.

Not modelled in v1 (documented so it is a conscious omission): the small variable
exchange / clearing / regulatory pass-through fees IBKR adds on top. Add them later if
you need cent-accurate commissions.
"""



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
# per_share:     commission per share. For TIERED this is the lowest-volume band rate
#                (the band-0 fallback); the effective tiered rate is resolved from
#                ``STOCK_TIERED_BANDS`` by ``stock_tiered_per_share`` based on the
#                account's cumulative monthly share volume. For FIXED it is a flat rate.
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


# Tiered stock per-share rate is a function of cumulative monthly share volume. Each
# band is ``(lower_bound_shares, per_share_rate)``; the rate applied is that of the
# highest band whose ``lower_bound`` the cumulative volume reaches. Lower bounds are the
# first share count entering each tier (e.g. 300,001 starts the 0.0020 tier), matching
# IBKR's published "≤ 300,000 / 300,001 – 3,000,000 / ..." ranges. Source: IBKR
# "Commissions Stocks" page, US Tiered column.
STOCK_TIERED_BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0"), Decimal("0.0035")),  # <= 300,000 shares/month
    (Decimal("300001"), Decimal("0.0020")),  # 300,001 - 3,000,000
    (Decimal("3000001"), Decimal("0.0015")),  # 3,000,001 - 20,000,000
    (Decimal("20000001"), Decimal("0.0010")),  # 20,000,001 - 100,000,000
    (Decimal("100000001"), Decimal("0.0005")),  # > 100,000,000
)


def stock_tiered_per_share(cumulative_shares: Decimal) -> Decimal:
    """Return the tiered per-share stock rate for a cumulative monthly volume.

    Args:
        cumulative_shares: The account's cumulative share volume for the current
            month (including the order being priced), as a decimal.

    Returns:
        The per-share commission rate for the tier the volume falls into.

    """
    # Bands are ascending by lower bound; return the rate of the highest band reached.
    rate = STOCK_TIERED_BANDS[0][1]
    for lower_bound, band_rate in STOCK_TIERED_BANDS:
        if cumulative_shares >= lower_bound:
            rate = band_rate
        else:
            break
    return rate


# --- US options -----------------------------------------------------------------------
# Fixed pricing is a flat per-contract rate. Tiered pricing is two-dimensional: the
# per-contract rate depends on BOTH the account's cumulative monthly CONTRACT volume and
# the option premium. See ``OPTION_TIERED_BANDS``.
OPTION_FIXED: dict[str, Decimal] = {
    "per_contract": Decimal("0.65"),
    "min_per_order": Decimal("1.00"),
}

OPTION_TIERED_MIN_PER_ORDER = Decimal("1.00")

# Two-dimensional tiered options table. Each entry is
# ``(monthly_contracts_lower_bound, premium_bands)`` ordered ascending by monthly
# contracts; the entry with the highest ``lower_bound`` the cumulative volume reaches
# applies. ``premium_bands`` is a tuple of ``(premium_gte, per_contract_rate)``
# evaluated top-down: the first whose threshold the option premium reaches sets the
# rate. Source: IBKR "Commissions Options" page, US Tiered (IBKR Pro) column.
OPTION_TIERED_BANDS: tuple[tuple[Decimal, tuple[tuple[Decimal, Decimal], ...]], ...] = (
    (
        Decimal("0"),  # <= 10,000 contracts/month
        (
            (Decimal("0.10"), Decimal("0.65")),  # premium >= 0.10
            (Decimal("0.05"), Decimal("0.50")),  # 0.05 <= premium < 0.10
            (Decimal("0.00"), Decimal("0.25")),  # premium < 0.05
        ),
    ),
    (
        Decimal("10001"),  # 10,001 - 50,000
        (
            (Decimal("0.05"), Decimal("0.50")),  # premium >= 0.05
            (Decimal("0.00"), Decimal("0.25")),  # premium < 0.05
        ),
    ),
    (
        Decimal("50001"),  # 50,001 - 100,000
        (
            (Decimal("0.00"), Decimal("0.25")),  # all premiums
        ),
    ),
    (
        Decimal("100001"),  # >= 100,001
        (
            (Decimal("0.00"), Decimal("0.15")),  # all premiums
        ),
    ),
)


def option_tiered_per_contract(
    premium: Decimal,
    cumulative_contracts: Decimal = Decimal("0"),
) -> Decimal:
    """Return the tiered per-contract options rate for a premium and monthly volume.

    Args:
        premium: The option premium (fill price) as a decimal.
        cumulative_contracts: The account's cumulative monthly CONTRACT volume
            (including the order being priced), as a decimal. Defaults to 0 (the
            lowest volume tier), preserving the historical single-argument behavior.

    Returns:
        The per-contract commission rate.

    """
    # Select the volume tier: the highest ``lower_bound`` the cumulative volume reaches.
    premium_bands = OPTION_TIERED_BANDS[0][1]
    for lower_bound, bands in OPTION_TIERED_BANDS:
        if cumulative_contracts >= lower_bound:
            premium_bands = bands
        else:
            break
    # Within that tier, the first ``premium_gte`` the premium reaches sets the rate.
    for premium_gte, rate in premium_bands:
        if premium >= premium_gte:
            return rate
    return premium_bands[-1][1]
