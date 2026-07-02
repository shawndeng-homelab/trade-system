"""IBKR commission fee model for backtests.

IBKR instruments are parsed by NautilusTrader with ``maker_fee = taker_fee = 0``, so the
generic ``MakerTakerFeeModel`` charges nothing and backtests become unrealistic. This
model reproduces IBKR's real structure: per share (stocks/ETFs) or per contract (options)
with a per-order minimum and, for stocks, a value cap, under either Tiered or Fixed
pricing.

Tiered stock pricing is monthly-volume tiered: the per-share rate drops as the account's
cumulative monthly share volume crosses the published breakpoints (see
``schedule.STOCK_TIERED_BANDS``). The model tracks that cumulative volume per calendar
month from each fill's ``order.ts_init``; pass ``monthly_volume`` in the config to fix it
to a constant for deterministic, reproducible backtests.

Per-order semantics vs per-fill calls
-------------------------------------
``get_commission`` is called once per fill, but IBKR's minimum and cap are per order.
This model approximates that: the per-order minimum is applied only on the first fill of
an order (detected via ``order.filled_qty == 0``), and the stock value cap is applied per
fill. That matches single-fill orders exactly and is a close approximation for partially
filled orders. The tiered per-share rate is resolved from the cumulative monthly volume
**including** the current fill, so a whole fill is billed at one rate (IBKR bills a whole
order at the rate of the tier it lands in, not marginally within an order). Orders
straddling a month boundary or a partial fill across tiers are approximations.
"""



from datetime import UTC
from datetime import datetime
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
from trade_system_venues.ibkr.schedule import stock_tiered_per_share


class IBKRFeeModelConfig(FeeModelConfig, frozen=True):
    """Configuration for ``IBKRFeeModel``.

    Attributes:
        pricing: One of ``"tiered"`` or ``"fixed"``.
        asset_class: Explicit asset-class override (``"stock"`` or ``"option"``). When
            ``None`` the class is inferred from the instrument type.
        monthly_volume: Fixed cumulative monthly share volume used to resolve the tiered
            per-share rate. When set, the rate is constant across the whole backtest
            (deterministic, reproducible) and no per-month state is accumulated. When
            ``None`` (default), the model accumulates shares per calendar month from
            each fill's ``order.ts_init`` and resolves the rate from the running total.
            Only affects tiered stock pricing.
        monthly_contracts: Fixed cumulative monthly CONTRACT volume used to resolve the
            tiered options per-contract rate (the monthly-contracts dimension of the
            two-dimensional tiered options table). Same override semantics as
            ``monthly_volume``. Only affects tiered options pricing.

    """

    pricing: str = TIERED
    asset_class: str | None = None
    monthly_volume: Decimal | None = None
    monthly_contracts: Decimal | None = None


class IBKRFeeModel(FeeModel):
    """IBKR commission model for US stocks/ETFs and options.

    Args:
        config: The fee model configuration.

    """

    def __init__(self, config: IBKRFeeModelConfig | None = None) -> None:
        """Initialize the fee model, defaulting to tiered pricing when no config given."""
        self._config = config or IBKRFeeModelConfig()
        # Cumulative monthly share volume keyed by (year, month), used to resolve the
        # tiered per-share rate when ``monthly_volume`` is not pinned in the config.
        self._monthly_shares: dict[tuple[int, int], Decimal] = {}
        # Cumulative monthly CONTRACT volume keyed by (year, month), used to resolve the
        # tiered options per-contract rate when ``monthly_contracts`` is not pinned.
        self._monthly_contracts: dict[tuple[int, int], Decimal] = {}

    def reset(self) -> None:
        """Clear accumulated monthly volume state.

        Call between independent backtest runs that reuse the same model instance so
        cumulative volume from a prior run does not leak into the tier resolution.
        """
        self._monthly_shares = {}
        self._monthly_contracts = {}

    def _cumulative_monthly_shares(self, order: Order, fill_qty: Decimal) -> Decimal:
        """Return the cumulative monthly share volume including this fill.

        When ``config.monthly_volume`` is set it is returned as-is (no state mutation).
        Otherwise the fill quantity is accumulated into the bucket for the calendar
        month of ``order.ts_init`` and the new running total is returned.

        """
        if self._config.monthly_volume is not None:
            return self._config.monthly_volume
        # ``ts_init`` is in nanoseconds; convert to seconds for datetime. Use UTC so the
        # month bucket is independent of the host's local timezone.
        ts_seconds = int(order.ts_init) // 1_000_000_000
        dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
        key = (dt.year, dt.month)
        cumulative = self._monthly_shares.get(key, Decimal("0")) + fill_qty
        self._monthly_shares[key] = cumulative
        return cumulative

    def _cumulative_monthly_contracts(self, order: Order, fill_qty: Decimal) -> Decimal:
        """Return the cumulative monthly contract volume including this fill.

        Symmetric to ``_cumulative_monthly_shares`` but for options contracts, used to
        resolve the monthly-contracts dimension of the tiered options table.

        """
        if self._config.monthly_contracts is not None:
            return self._config.monthly_contracts
        ts_seconds = int(order.ts_init) // 1_000_000_000
        dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
        key = (dt.year, dt.month)
        cumulative = self._monthly_contracts.get(key, Decimal("0")) + fill_qty
        self._monthly_contracts[key] = cumulative
        return cumulative

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

    def _stock_commission(
        self,
        qty: Decimal,
        px: Decimal,
        first_fill: bool,
        cumulative_monthly_shares: Decimal | None = None,
    ) -> Decimal:
        """Return the stock commission for a single fill.

        For tiered pricing, ``cumulative_monthly_shares`` resolves the per-share rate
        from the volume bands; when ``None`` (e.g. unit tests calling directly) the
        lowest-volume band rate is used.
        """
        rules = schedule.STOCK_RULES[self._config.pricing]
        if self._config.pricing == TIERED and cumulative_monthly_shares is not None:
            per_share = stock_tiered_per_share(cumulative_monthly_shares)
        else:
            per_share = rules["per_share"]
        commission = qty * per_share
        commission = min(commission, qty * px * rules["max_pct"])  # value cap (per fill)
        if first_fill:
            commission = max(commission, rules["min_per_order"])  # min floors the order
        return commission

    def _option_commission(
        self,
        qty: Decimal,
        px: Decimal,
        first_fill: bool,
        cumulative_monthly_contracts: Decimal | None = None,
    ) -> Decimal:
        """Return the options commission for a single fill.

        For tiered pricing, ``cumulative_monthly_contracts`` resolves the monthly-
        contracts dimension of the two-dimensional tiered table (premium is taken from
        ``px``); when ``None`` (e.g. unit tests calling directly) the lowest volume tier
        is used.
        """
        if self._config.pricing == FIXED:
            per_contract = schedule.OPTION_FIXED["per_contract"]
            min_per_order = schedule.OPTION_FIXED["min_per_order"]
        else:
            cumulative = cumulative_monthly_contracts if cumulative_monthly_contracts is not None else Decimal("0")
            per_contract = schedule.option_tiered_per_contract(px, cumulative)
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
            cumulative = self._cumulative_monthly_shares(order, qty) if self._config.pricing == TIERED else None
            commission = self._stock_commission(qty, px, first_fill, cumulative)
        elif asset_class == OPTION:
            cumulative = self._cumulative_monthly_contracts(order, qty) if self._config.pricing == TIERED else None
            commission = self._option_commission(qty, px, first_fill, cumulative)
        else:
            raise ValueError(
                f"unsupported asset class {asset_class!r} for IBKRFeeModel (supported: 'stock', 'option')",
            )

        return Money(commission, instrument.quote_currency)
