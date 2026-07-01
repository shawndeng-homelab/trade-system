"""IBKR commission schedules for tiered and fixed pricing across asset classes.

Unlike crypto maker/taker percentages, IBKR commissions are structured per share /
per contract / per notional-bps, with a per-order minimum and (for some classes) a cap
expressed as a percentage of trade value. Rules differ per asset class and per pricing
plan (Tiered vs Fixed).

Sources (verify and date-stamp when populating):

- Stocks/ETFs:  https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- Futures:      https://www.interactivebrokers.com/en/pricing/commissions-futures.php
- Options:      https://www.interactivebrokers.com/en/pricing/commissions-options.php
- Forex:        https://www.interactivebrokers.com/en/pricing/commissions-spot-currencies.php

TODO(step 3): populate per-class schedules for both pricing plans.
"""

from __future__ import annotations


# Pricing plan identifiers used by ``IBKRFeeModelConfig.pricing``.
TIERED = "tiered"
FIXED = "fixed"

# Asset class identifiers used to route to the correct schedule.
STOCK = "stock"
FUTURE = "future"
OPTION = "option"
FOREX = "forex"

# Placeholder: per (pricing_plan, asset_class) commission rule set, filled in step 3.
COMMISSION_RULES: dict[tuple[str, str], object] = {}
