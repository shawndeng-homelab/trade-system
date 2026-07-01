"""Funding-data plumbing that gives backtest and live the same ``FundingRateUpdate`` feed.

Two responsibilities:

- **Live normalization** — Binance emits ``BinanceFuturesMarkPriceUpdate`` (funding rate
  embedded). Convert it to the core ``FundingRateUpdate`` so ``BinanceFundingActor``
  subscribes to one type in both backtest and live (research-to-live parity).
- **Historical loading** — pull ``GET /fapi/v1/fundingRate`` history (reusing the
  NautilusTrader Binance HTTP client) and write ``FundingRateUpdate`` records into a
  ``ParquetDataCatalog`` for backtests.
"""

from __future__ import annotations

from nautilus_trader.adapters.binance.futures.types import BinanceFuturesMarkPriceUpdate
from nautilus_trader.model.data import FundingRateUpdate


# Binance USDⓈ-M / COIN-M perpetuals settle funding every 8 hours.
DEFAULT_FUNDING_INTERVAL_MINS = 8 * 60


def mark_price_to_funding_rate(update: BinanceFuturesMarkPriceUpdate) -> FundingRateUpdate:
    """Convert a Binance mark-price update into a core ``FundingRateUpdate``.

    Args:
        update: The live mark-price update carrying the embedded funding rate.

    Returns:
        The converted core funding-rate update.

    """
    raise NotImplementedError("mark_price_to_funding_rate is implemented in a later step")
