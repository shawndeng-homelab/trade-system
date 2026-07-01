"""Tests for the IBKR commission fee model."""

from decimal import Decimal

import pytest
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from trade_system_venues.ibkr.fee import IBKRFeeModel
from trade_system_venues.ibkr.fee import IBKRFeeModelConfig
from trade_system_venues.ibkr.schedule import option_tiered_per_contract


class _OrderStub:
    """Minimal stand-in for an Order exposing only what the fee model reads."""

    def __init__(self, filled_qty: int = 0) -> None:
        self.filled_qty = filled_qty


# --- schedule --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("premium", "expected"),
    [
        (Decimal("0.50"), Decimal("0.65")),
        (Decimal("0.10"), Decimal("0.65")),
        (Decimal("0.07"), Decimal("0.50")),
        (Decimal("0.05"), Decimal("0.50")),
        (Decimal("0.03"), Decimal("0.25")),
        (Decimal("0.00"), Decimal("0.25")),
    ],
)
def test_option_tiered_bands(premium, expected):
    """Tiered per-contract rate follows the premium bands."""
    assert option_tiered_per_contract(premium) == expected


# --- stock commission ------------------------------------------------------------------


def test_stock_tiered_per_share():
    """Tiered stocks charge per-share above the minimum and below the cap."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 1000 * 0.0035 = 3.50; min 0.35, cap 1% * 150000 = 1500 -> 3.50
    assert model._stock_commission(Decimal("1000"), Decimal("150"), first_fill=True) == Decimal("3.50")


def test_stock_min_per_order_floor():
    """A small tiered stock order is floored at the per-order minimum on the first fill."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 10 * 0.0035 = 0.035 -> floored to 0.35
    assert model._stock_commission(Decimal("10"), Decimal("150"), first_fill=True) == Decimal("0.35")


def test_stock_value_cap():
    """A low-priced stock order is capped at 1% of trade value."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 1000 * 0.0035 = 3.50; cap = 1% * (1000 * 0.10) = 1.00 -> 1.00
    assert model._stock_commission(Decimal("1000"), Decimal("0.10"), first_fill=True) == Decimal("1.00")


def test_stock_no_min_on_subsequent_fill():
    """The per-order minimum is not re-applied on later fills."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    assert model._stock_commission(Decimal("10"), Decimal("150"), first_fill=False) == Decimal("0.035")


def test_stock_fixed_pricing():
    """Fixed stocks charge 0.005/share with a 1.00 minimum."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="fixed"))
    assert model._stock_commission(Decimal("1000"), Decimal("150"), first_fill=True) == Decimal("5.00")
    assert model._stock_commission(Decimal("10"), Decimal("150"), first_fill=True) == Decimal("1.00")


# --- option commission -----------------------------------------------------------------


def test_option_fixed_pricing():
    """Fixed options charge 0.65/contract with a 1.00 minimum."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="fixed"))
    assert model._option_commission(Decimal("10"), Decimal("2.50"), first_fill=True) == Decimal("6.50")
    assert model._option_commission(Decimal("1"), Decimal("2.50"), first_fill=True) == Decimal("1.00")


def test_option_tiered_premium_based():
    """Tiered options price per-contract by premium band."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # premium 0.03 -> 0.25/contract, 100 contracts -> 25.00
    assert model._option_commission(Decimal("100"), Decimal("0.03"), first_fill=True) == Decimal("25.00")


# --- asset class inference -------------------------------------------------------------


def test_asset_class_inference():
    """Asset class is inferred from the instrument type."""
    model = IBKRFeeModel()
    assert model._asset_class(TestInstrumentProvider.equity()) == "stock"
    assert model._asset_class(TestInstrumentProvider.aapl_option()) == "option"


def test_asset_class_override():
    """An explicit asset_class config overrides inference."""
    model = IBKRFeeModel(IBKRFeeModelConfig(asset_class="option"))
    assert model._asset_class(TestInstrumentProvider.equity()) == "option"


# --- end-to-end get_commission ---------------------------------------------------------


def test_get_commission_stock():
    """End-to-end stock commission returns Money in the instrument's quote currency."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    equity = TestInstrumentProvider.equity()
    commission = model.get_commission(
        order=_OrderStub(filled_qty=0),
        fill_qty=Quantity.from_int(1000),
        fill_px=Price.from_str("150.00"),
        instrument=equity,
    )
    assert commission.as_decimal() == Decimal("3.50")
    assert commission.currency == equity.quote_currency


def test_get_commission_option():
    """End-to-end option commission uses per-contract pricing."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="fixed"))
    option = TestInstrumentProvider.aapl_option()
    commission = model.get_commission(
        order=_OrderStub(filled_qty=0),
        fill_qty=Quantity.from_int(10),
        fill_px=Price.from_str("2.50"),
        instrument=option,
    )
    assert commission.as_decimal() == Decimal("6.50")
    assert commission.currency == option.quote_currency


# --- scaffold-level sanity -------------------------------------------------------------


def test_ibkr_fee_model_is_fee_model():
    """IBKRFeeModel subclasses the NautilusTrader FeeModel base."""
    assert issubclass(IBKRFeeModel, FeeModel)


def test_ibkr_fee_model_config_defaults():
    """Config defaults to tiered pricing with inferred asset class."""
    config = IBKRFeeModelConfig()
    assert config.pricing == "tiered"
    assert config.asset_class is None
