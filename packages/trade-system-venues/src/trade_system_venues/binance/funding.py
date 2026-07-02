"""Binance perpetual funding-rate settlement.

Settles funding against open positions at each 8h funding boundary using the shared
``FinancingSettlementActor`` ledger. The cashflow per position is::

    cashflow = -(position_signed_size * mark_price * funding_rate)

Longs pay when the rate is positive and receive when negative; shorts are the mirror.
"""



from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId

from trade_system_venues.core.financing import FinancingConfig
from trade_system_venues.core.financing import FinancingSettlementActor


class BinanceFundingConfig(FinancingConfig, frozen=True):
    """Configuration for ``BinanceFundingActor``.

    Attributes:
        use_mark_price: Whether to value positions at the venue mark price (recommended)
            versus the last trade price when computing the funding cashflow.

    """

    use_mark_price: bool = True


class BinanceFundingActor(FinancingSettlementActor):
    """Settle Binance perpetual funding into the financing ledger.

    Args:
        config: The funding configuration.

    """

    def on_start(self) -> None:
        """Subscribe to normalized ``FundingRateUpdate`` data for configured instruments."""
        raise NotImplementedError("on_start is implemented in a later step")

    def _compute_cashflow(self, instrument_id: InstrumentId, rate: Decimal, ts_ns: int) -> Decimal:
        """Return ``-(signed_size * mark_price * funding_rate)`` for the position."""
        raise NotImplementedError("_compute_cashflow is implemented in a later step")
