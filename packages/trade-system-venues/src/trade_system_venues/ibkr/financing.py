"""IBKR financing: margin interest on borrowed cash and short-borrow fees.

IBKR has no funding rate. Its periodic carrying costs are margin interest (on debit
balances from leveraged longs) and stock-borrow fees (on short positions), both accrued
daily on an annualized rate with a day-count convention. This reuses the shared
``FinancingSettlementActor`` ledger with a daily settlement timer::

    cashflow = -(borrowed_or_short_value * annual_rate * days / day_count)
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId

from trade_system_venues.core.financing import FinancingConfig
from trade_system_venues.core.financing import FinancingSettlementActor


class IBKRFinancingConfig(FinancingConfig, frozen=True):
    """Configuration for ``IBKRFinancingActor``.

    Attributes:
        day_count: Day-count denominator for annualized-rate accrual.

    """

    day_count: int = 360


class IBKRFinancingActor(FinancingSettlementActor):
    """Accrue IBKR margin interest and short-borrow fees into the financing ledger.

    Args:
        config: The financing configuration.

    """

    def on_start(self) -> None:
        """Arm a daily settlement timer and prepare the borrow/interest rate source."""
        raise NotImplementedError("on_start is implemented in a later step")

    def _compute_cashflow(self, instrument_id: InstrumentId, rate: Decimal, ts_ns: int) -> Decimal:
        """Return the daily interest/borrow accrual for the position."""
        raise NotImplementedError("_compute_cashflow is implemented in a later step")
