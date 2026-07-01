"""Shared periodic-cost settlement machinery (funding, margin interest, borrow fees).

NautilusTrader does not settle perpetual funding or margin/borrow financing against
accounts in either backtest or live contexts. ``FinancingSettlementActor`` fills that
gap: it settles a periodic cashflow against open positions and records the result in an
independent ledger, without mutating account balances (the MVP overlay approach).

Venue-specific subclasses provide the rate source and the settlement formula:

- Binance funding: ``size * mark_price * funding_rate`` at each 8h funding boundary.
- IBKR financing: ``borrowed * annual_rate * days / day_count`` accrued daily, plus
  short-borrow fees.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import InstrumentId


class FinancingConfig(ActorConfig, frozen=True):
    """Base configuration for ``FinancingSettlementActor`` subclasses.

    Parameters
    ----------
    instrument_ids : list[str] or None, default None
        Instruments to settle financing for. When ``None`` the actor settles every
        instrument for which a position is held.

    """

    instrument_ids: list[str] | None = None


class FinancingEvent(Data):
    """A single settled financing cashflow, published for analysis and record-keeping.

    Parameters
    ----------
    instrument_id : InstrumentId
        The instrument the cashflow applies to.
    amount : Decimal
        The settled cashflow in the settlement currency. Positive is a credit to the
        account, negative is a debit.
    ts_event : int
        UNIX timestamp (nanoseconds) of the settlement.
    ts_init : int
        UNIX timestamp (nanoseconds) when the object was initialized.

    """

    def __init__(
        self,
        instrument_id: InstrumentId,
        amount: Decimal,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.instrument_id = instrument_id
        self.amount = amount
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        """UNIX timestamp (nanoseconds) when the settlement occurred."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX timestamp (nanoseconds) when the object was initialized."""
        return self._ts_init


class FinancingSettlementActor(Actor):
    """Settle periodic financing cashflows against open positions into a ledger.

    This base class owns the ledger, the settlement dispatch, and the ``FinancingEvent``
    publication. Subclasses implement the rate subscription and the per-position formula.

    Parameters
    ----------
    config : FinancingConfig
        The financing configuration.

    """

    def __init__(self, config: FinancingConfig) -> None:
        super().__init__(config)
        self._ledger: dict[InstrumentId, Decimal] = {}

    def cumulative_financing(self) -> Decimal:
        """Return the total settled financing across all instruments."""
        return sum(self._ledger.values(), Decimal(0))

    def on_start(self) -> None:
        """Subscribe to the rate source and arm settlement timers."""
        raise NotImplementedError("on_start is implemented by venue subclasses")

    def _compute_cashflow(self, instrument_id: InstrumentId, rate: Decimal, ts_ns: int) -> Decimal:
        """Return the financing cashflow for one instrument at a settlement time.

        Parameters
        ----------
        instrument_id : InstrumentId
            The instrument to settle.
        rate : Decimal
            The applicable rate for this settlement period.
        ts_ns : int
            UNIX timestamp (nanoseconds) of the settlement.

        Returns
        -------
        Decimal
            The cashflow (positive credit, negative debit).

        """
        raise NotImplementedError("_compute_cashflow is implemented by venue subclasses")

    def _settle(self, instrument_id: InstrumentId, rate: Decimal, ts_ns: int) -> None:
        """Compute, record, and publish a single financing settlement."""
        raise NotImplementedError("_settle is implemented in a later step")
