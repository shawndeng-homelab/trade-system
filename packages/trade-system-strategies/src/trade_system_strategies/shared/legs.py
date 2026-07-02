"""Multi-leg position state machine and reconciliation helpers.

NautilusTrader has no native client-side combo order for backtests, so multi-leg
strategies submit each leg as a separate order and reconcile fills here. A
``LegGroup`` tracks the intended legs vs. their fill state, so a strategy can tell
when a whole combo is filled and what its blended cost is.

The types here are deliberately engine-free plain Python so they can be unit-tested
and reused in research notebooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal


@dataclass(frozen=True)
class LegSpec:
    """A single intended leg of a multi-leg combo.

    Attributes:
        instrument_id: The option (or underlying) instrument id, e.g. ``"SPY.ARCA"``.
        side: ``"BUY"`` or ``"SELL"``.
        quantity: Number of contracts/shares as a decimal.
        limit_price: Optional limit price per unit; ``None`` means market.

    """

    instrument_id: str
    side: str
    quantity: Decimal
    limit_price: Decimal | None = None

    @property
    def signed_quantity(self) -> Decimal:
        """Return the quantity with sign: positive for BUY, negative for SELL."""
        sign = Decimal("1") if self.side.upper() == "BUY" else Decimal("-1")
        return sign * self.quantity


@dataclass
class LegFill:
    """Tracks the filled state of one leg."""

    spec: LegSpec
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")

    @property
    def is_complete(self) -> bool:
        """Whether this leg is fully filled."""
        return self.filled_qty >= self.spec.quantity

    @property
    def signed_filled_qty(self) -> Decimal:
        """Filled quantity with the leg's side sign."""
        sign = Decimal("1") if self.spec.side.upper() == "BUY" else Decimal("-1")
        return sign * self.filled_qty

    def apply_fill(self, fill_qty: Decimal, fill_price: Decimal) -> None:
        """Accumulate a fill into this leg's running average price."""
        total_qty = self.filled_qty + fill_qty
        if total_qty == 0:
            self.avg_fill_price = Decimal("0")
        else:
            self.avg_fill_price = (self.avg_fill_price * self.filled_qty + fill_price * fill_qty) / total_qty
        self.filled_qty = total_qty


@dataclass
class LegGroup:
    """A reconciled multi-leg combo: intended legs plus their fill state.

    Use :meth:`apply_fill` from a strategy's ``on_order_filled`` to record each leg's
    fills, keyed by the client order id assigned at submission time. The group exposes
    whether the whole combo is complete and its net cost (premium paid/received).

    """

    name: str
    legs: list[LegFill] = field(default_factory=list)
    # Maps the client order id used to submit a leg -> index into ``legs``.
    _order_to_leg: dict[str, int] = field(default_factory=dict)

    def add_leg(self, spec: LegSpec, client_order_id: str) -> None:
        """Register a leg and the client order id it was submitted under."""
        self._order_to_leg[client_order_id] = len(self.legs)
        self.legs.append(LegFill(spec=spec))

    def apply_fill(self, client_order_id: str, fill_qty: Decimal, fill_price: Decimal) -> None:
        """Record a fill for the leg submitted under ``client_order_id``."""
        idx = self._order_to_leg[client_order_id]
        self.legs[idx].apply_fill(fill_qty, fill_price)

    @property
    def is_complete(self) -> bool:
        """Whether every leg in the group is fully filled."""
        return bool(self.legs) and all(leg.is_complete for leg in self.legs)

    @property
    def net_cost(self) -> Decimal:
        """Net premium: positive = debit paid, negative = credit received.

        Computed as ``sum(signed_qty * avg_fill_price)`` across legs.
        """
        return sum(
            (leg.signed_filled_qty * leg.avg_fill_price for leg in self.legs),
            start=Decimal("0"),
        )
