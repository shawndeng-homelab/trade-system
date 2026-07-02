"""Binance maker/taker fee schedules (VIP tiers and BNB discounts).

Rates are sourced from Binance's published fee schedules and grouped by account type.
Keep the data here (separate from calculation logic) so it is easy to audit and update.

Sources (verify and date-stamp when populating):

- Spot:        https://www.binance.com/en/fee/trading
- USDⓈ-M:      https://www.binance.com/en/fee/futureFee
- COIN-M:      https://www.binance.com/en/fee/futureFee

TODO(step 2): populate the tier tables and BNB discount constants.
"""



from decimal import Decimal


# Account type identifiers used by ``BinanceFeeModelConfig.account_type``.
SPOT = "spot"
USDT_FUTURES = "usdt_futures"
COIN_FUTURES = "coin_futures"

# Placeholder: replaced with real (maker, taker) rows per VIP tier in step 2.
FEE_TIERS: dict[str, tuple[tuple[Decimal, Decimal], ...]] = {}

# Placeholder: BNB spot discount (25%) and futures discount (10%) as multipliers.
BNB_DISCOUNT: dict[str, Decimal] = {}
