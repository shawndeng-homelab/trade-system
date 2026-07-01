"""IBKR commission fee model for backtests.

IBKR instruments are parsed by NautilusTrader with ``maker_fee = taker_fee = 0``, so the
generic ``MakerTakerFeeModel`` charges nothing and backtests become unrealistic. This
model reproduces IBKR's real structure: per share / per contract / per notional-bps with
per-order minimums and value caps, routed by asset class, under either Tiered or Fixed
pricing.
"""

from __future__ import annotations

from nautilus_trader.backtest.config import FeeModelConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import Order

from trade_system_venues.ibkr.schedule import TIERED


class IBKRFeeModelConfig(FeeModelConfig, frozen=True):
    """Configuration for ``IBKRFeeModel``.

    Args:
        pricing: One of ``"tiered"`` or ``"fixed"``.
        asset_class: Explicit asset-class override (``"stock"``, ``"future"``,
            ``"option"``, ``"forex"``). When ``None`` the class is inferred from the
            instrument.

    """

    pricing: str = TIERED
    asset_class: str | None = None


class IBKRFeeModel(FeeModel):
    """IBKR commission model spanning stocks, futures, options, and forex.

    Args:
        config: The fee model configuration.

    """

    def __init__(self, config: IBKRFeeModelConfig | None = None) -> None:
        """Initialize the fee model, defaulting to tiered pricing when no config given."""
        self._config = config or IBKRFeeModelConfig()

    def _asset_class(self, instrument: Instrument) -> str:
        """Return the configured or inferred asset class for an instrument."""
        raise NotImplementedError("_asset_class is implemented in a later step")

    def get_commission(
        self,
        order: Order,
        fill_qty: Quantity,
        fill_px: Price,
        instrument: Instrument,
    ) -> Money:
        """Return the commission for a fill (see ``FeeModel.get_commission``)."""
        raise NotImplementedError("get_commission is implemented in a later step")
