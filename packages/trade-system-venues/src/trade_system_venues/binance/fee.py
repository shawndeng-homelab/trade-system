"""Binance maker/taker commission fee model for backtests.

Subclasses ``FeeModel`` so it plugs into ``BacktestEngine.add_venue(fee_model=...)`` and
the standard ``FeeModelFactory`` / ``ImportableFeeModelConfig`` path. The generic
``MakerTakerFeeModel`` only reads ``instrument.maker_fee`` / ``instrument.taker_fee``;
this model adds Binance VIP tiers, BNB discounts, and spot / USDⓈ-M / COIN-M handling
(including inverse-contract commission currency).
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.config import FeeModelConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import Order

from trade_system_venues.binance.schedule import USDT_FUTURES


class BinanceFeeModelConfig(FeeModelConfig, frozen=True):
    """Configuration for ``BinanceFeeModel``.

    Parameters
    ----------
    account_type : str, default "usdt_futures"
        One of ``"spot"``, ``"usdt_futures"``, ``"coin_futures"``.
    vip_level : int, default 0
        VIP tier used to look up maker/taker rates from the fee schedule.
    use_bnb_discount : bool, default False
        Whether to apply the BNB fee discount (spot 25% / futures 10%).
    maker_fee : str or None, default None
        Explicit maker rate override (decimal fraction). Bypasses the tier table.
    taker_fee : str or None, default None
        Explicit taker rate override (decimal fraction). Bypasses the tier table.

    """

    account_type: str = USDT_FUTURES
    vip_level: int = 0
    use_bnb_discount: bool = False
    maker_fee: str | None = None
    taker_fee: str | None = None


class BinanceFeeModel(FeeModel):
    """Binance maker/taker fee model with VIP tiers and BNB discounts.

    Parameters
    ----------
    config : BinanceFeeModelConfig
        The fee model configuration.

    """

    def __init__(self, config: BinanceFeeModelConfig | None = None) -> None:
        self._config = config or BinanceFeeModelConfig()

    def _resolve_rate(self, liquidity_side: LiquiditySide) -> Decimal:
        """Resolve the effective fee rate for a fill's liquidity side."""
        raise NotImplementedError("_resolve_rate is implemented in a later step")

    def get_commission(
        self,
        order: Order,
        fill_qty: Quantity,
        fill_px: Price,
        instrument: Instrument,
    ) -> Money:
        """Return the commission for a fill (see ``FeeModel.get_commission``)."""
        raise NotImplementedError("get_commission is implemented in a later step")
