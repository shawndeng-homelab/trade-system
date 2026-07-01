"""IBKR commission fee model for backtests.

IBKR instruments are parsed by NautilusTrader with ``maker_fee = taker_fee = 0``, so the
generic ``MakerTakerFeeModel`` charges nothing and backtests become unrealistic. This
model reproduces IBKR's real structure: per share (stocks/ETFs) or per contract (options)
with a per-order minimum and, for stocks, a value cap, under either Tiered or Fixed
pricing.

Per-order semantics vs per-fill calls
-------------------------------------
``get_commission`` is called once per fill, but IBKR's minimum and cap are per order.
This model approximates that: the per-order minimum is applied only on the first fill of
an order (detected via ``order.filled_qty == 0``), and the stock value cap is applied per
fill. That matches single-fill orders exactly and is a close approximation for partially
filled orders.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.config import FeeModelConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import Order

from trade_system_venues.ibkr import schedule
from trade_system_venues.ibkr.schedule import FIXED
from trade_system_venues.ibkr.schedule import OPTION
from trade_system_venues.ibkr.schedule import STOCK
from trade_system_venues.ibkr.schedule import TIERED


class IBKRFeeModelConfig(FeeModelConfig, frozen=True):
    """Configuration for ``IBKRFeeModel``.

    Attributes:
        pricing: One of ``"tiered"`` or ``"fixed"``.
        asset_class: Explicit asset-class override (``"stock"`` or ``"option"``). When
            ``None`` the class is inferred from the instrument type.

    """

    pricing: str = TIERED
    asset_class: str | None = None


class IBKRFeeModel(FeeModel):
    """IBKR commission model for US stocks/ETFs and options.

    Args:
        config: The fee model configuration.

    """

    def __init__(self, config: IBKRFeeModelConfig | None = None) -> None:
        """Initialize the fee model, defaulting to tiered pricing when no config given."""
        self._config = config or IBKRFeeModelConfig()

    def _asset_class(self, instrument: Instrument) -> str:
        """Return the configured or inferred asset class for an instrument."""
        if self._config.asset_class is not None:
            return self._config.asset_class
        if isinstance(instrument, OptionContract):
            return OPTION
        if isinstance(instrument, Equity):
            return STOCK
        raise ValueError(
            f"cannot infer IBKR asset class for instrument type {type(instrument).__name__}; "
            "set `asset_class` explicitly in IBKRFeeModelConfig",
        )

    def _stock_commission(self, qty: Decimal, px: Decimal, first_fill: bool) -> Decimal:
        """Return the stock commission for a single fill."""
        rules = schedule.STOCK_RULES[self._config.pricing]
        commission = qty * rules["per_share"]
        commission = min(commission, qty * px * rules["max_pct"])  # value cap (per fill)
        if first_fill:
            commission = max(commission, rules["min_per_order"])  # min floors the order
        return commission

    def _option_commission(self, qty: Decimal, px: Decimal, first_fill: bool) -> Decimal:
        """Return the options commission for a single fill."""
        if self._config.pricing == FIXED:
            per_contract = schedule.OPTION_FIXED["per_contract"]
            min_per_order = schedule.OPTION_FIXED["min_per_order"]
        else:
            per_contract = schedule.option_tiered_per_contract(px)
            min_per_order = schedule.OPTION_TIERED_MIN_PER_ORDER
        commission = qty * per_contract
        if first_fill:
            commission = max(commission, min_per_order)
        return commission

    def get_commission(
        self,
        order: Order,
        fill_qty: Quantity,
        fill_px: Price,
        instrument: Instrument,
    ) -> Money:
        """Return the commission for a fill (see ``FeeModel.get_commission``)."""
        asset_class = self._asset_class(instrument)
        qty = Decimal(str(fill_qty))
        px = Decimal(str(fill_px))
        first_fill = order.filled_qty == 0

        if asset_class == STOCK:
            commission = self._stock_commission(qty, px, first_fill)
        elif asset_class == OPTION:
            commission = self._option_commission(qty, px, first_fill)
        else:
            raise ValueError(
                f"unsupported asset class {asset_class!r} for IBKRFeeModel (supported: 'stock', 'option')",
            )

        return Money(commission, instrument.quote_currency)
