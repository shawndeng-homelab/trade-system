"""Tests for the IBKR commission fee model."""

from datetime import UTC
from datetime import datetime
from decimal import Decimal

import pytest
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from trade_system_venues.ibkr.fee import IBKRFeeModel
from trade_system_venues.ibkr.fee import IBKRFeeModelConfig
from trade_system_venues.ibkr.schedule import option_tiered_per_contract
from trade_system_venues.ibkr.schedule import stock_tiered_per_share


def _ns(year: int, month: int, day: int = 15) -> int:
    """Return a nanosecond ts_init for the given UTC date (what Order.ts_init carries)."""
    return int(datetime(year, month, day, tzinfo=UTC).timestamp()) * 1_000_000_000


class _OrderStub:
    """Minimal stand-in for an Order exposing only what the fee model reads."""

    def __init__(self, filled_qty: int = 0, ts_init: int | None = None) -> None:
        self.filled_qty = filled_qty
        # Default to a fixed UTC timestamp so month-bucketing is deterministic.
        self.ts_init = ts_init if ts_init is not None else _ns(2024, 1)


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


# --- tiered volume bands ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("cumulative", "expected"),
    [
        (Decimal("0"), Decimal("0.0035")),
        (Decimal("1"), Decimal("0.0035")),
        (Decimal("300000"), Decimal("0.0035")),
        (Decimal("300001"), Decimal("0.0020")),
        (Decimal("3000000"), Decimal("0.0020")),
        (Decimal("3000001"), Decimal("0.0015")),
        (Decimal("20000000"), Decimal("0.0015")),
        (Decimal("20000001"), Decimal("0.0010")),
        (Decimal("100000000"), Decimal("0.0010")),
        (Decimal("100000001"), Decimal("0.0005")),
    ],
)
def test_stock_tiered_volume_bands(cumulative, expected):
    """The tiered per-share rate follows the monthly cumulative-volume bands."""
    assert stock_tiered_per_share(cumulative) == expected


def test_stock_tiered_low_volume_default():
    """Small monthly volume (the user's ~100-trade profile) stays at 0.0035/share."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 1000 * 0.0035 = 3.50; cumulative 1000 << 300,000 threshold
    commission = model._stock_commission(
        Decimal("1000"),
        Decimal("150"),
        first_fill=True,
        cumulative_monthly_shares=Decimal("1000"),
    )
    assert commission == Decimal("3.50")


def test_stock_tiered_crosses_threshold():
    """Crossing 300k cumulative shares drops the rate to 0.0020 (cap/min still apply)."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 1000 * 0.0020 = 2.00; min 0.35, cap 1% * 150000 = 1500 -> 2.00
    commission = model._stock_commission(
        Decimal("1000"),
        Decimal("150"),
        first_fill=True,
        cumulative_monthly_shares=Decimal("400000"),
    )
    assert commission == Decimal("2.00")


def test_stock_tiered_high_volume_override():
    """50M cumulative shares lands in the 0.0010 band."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # 1000 * 0.0010 = 1.00; min 0.35, cap 1500 -> 1.00
    commission = model._stock_commission(
        Decimal("1000"),
        Decimal("150"),
        first_fill=True,
        cumulative_monthly_shares=Decimal("50000000"),
    )
    assert commission == Decimal("1.00")


def test_monthly_volume_override_skips_state():
    """A pinned monthly_volume resolves the rate without accumulating internal state."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered", monthly_volume=Decimal("400000")))
    order = _OrderStub(filled_qty=0)
    cumulative = model._cumulative_monthly_shares(order, Decimal("1000"))
    assert cumulative == Decimal("400000")
    # State must remain untouched across calls.
    assert model._monthly_shares == {}


def test_monthly_accumulation_across_fills():
    """Accumulating fills within a month crosses the 300k threshold and lowers the rate."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    order_ts = _ns(2024, 1)
    # First fill: cumulative becomes 300000 -> still 0.0035 band.
    cum1 = model._cumulative_monthly_shares(_OrderStub(filled_qty=0, ts_init=order_ts), Decimal("300000"))
    assert cum1 == Decimal("300000")
    assert stock_tiered_per_share(cum1) == Decimal("0.0035")
    # Next fill pushes cumulative to 300001 -> drops to 0.0020 band.
    cum2 = model._cumulative_monthly_shares(_OrderStub(filled_qty=0, ts_init=order_ts), Decimal("1"))
    assert cum2 == Decimal("300001")
    assert stock_tiered_per_share(cum2) == Decimal("0.0020")


def test_monthly_accumulation_separate_months():
    """Volume is bucketed per calendar month, so a new month starts the counter at zero."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    jan = model._cumulative_monthly_shares(_OrderStub(filled_qty=0, ts_init=_ns(2024, 1)), Decimal("300000"))
    feb = model._cumulative_monthly_shares(_OrderStub(filled_qty=0, ts_init=_ns(2024, 2)), Decimal("1"))
    assert jan == Decimal("300000")
    assert feb == Decimal("1")  # February starts fresh, not 300001.


def test_reset_clears_state():
    """reset() zeroes the accumulated monthly volume for a clean re-run."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    model._cumulative_monthly_shares(_OrderStub(filled_qty=0), Decimal("1000"))
    assert model._monthly_shares != {}
    model.reset()
    assert model._monthly_shares == {}
    # After reset the next fill starts a fresh bucket.
    cum = model._cumulative_monthly_shares(_OrderStub(filled_qty=0), Decimal("500"))
    assert cum == Decimal("500")


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


# --- tiered options 2D bands (monthly contracts x premium) ----------------------------


@pytest.mark.parametrize(
    ("cumulative_contracts", "premium", "expected_rate"),
    [
        # <= 10,000 contracts/month
        (Decimal("0"), Decimal("0.03"), Decimal("0.25")),
        (Decimal("0"), Decimal("0.05"), Decimal("0.50")),
        (Decimal("0"), Decimal("0.07"), Decimal("0.50")),
        (Decimal("0"), Decimal("0.10"), Decimal("0.65")),
        (Decimal("10000"), Decimal("0.10"), Decimal("0.65")),
        # 10,001 - 50,000: premium >= 0.05 caps at 0.50 (not 0.65)
        (Decimal("10001"), Decimal("0.03"), Decimal("0.25")),
        (Decimal("10001"), Decimal("0.05"), Decimal("0.50")),
        (Decimal("10001"), Decimal("0.10"), Decimal("0.50")),
        (Decimal("50000"), Decimal("0.10"), Decimal("0.50")),
        # 50,001 - 100,000: all premiums 0.25
        (Decimal("50001"), Decimal("0.03"), Decimal("0.25")),
        (Decimal("50001"), Decimal("0.10"), Decimal("0.25")),
        (Decimal("100000"), Decimal("0.10"), Decimal("0.25")),
        # >= 100,001: all premiums 0.15
        (Decimal("100001"), Decimal("0.03"), Decimal("0.15")),
        (Decimal("100001"), Decimal("0.10"), Decimal("0.15")),
    ],
)
def test_option_tiered_2d_bands(cumulative_contracts, premium, expected_rate):
    """The tiered per-contract rate follows the 2D monthly-contracts x premium table."""
    assert option_tiered_per_contract(premium, cumulative_contracts) == expected_rate


def test_option_tiered_low_volume_default():
    """Small monthly volume (the user's ~100-trade profile) stays at the <=10k tier."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # premium 0.03 -> 0.25/contract, cumulative 100 << 10,000 threshold
    commission = model._option_commission(
        Decimal("100"),
        Decimal("0.03"),
        first_fill=True,
        cumulative_monthly_contracts=Decimal("100"),
    )
    assert commission == Decimal("25.00")


def test_option_tiered_crosses_contract_threshold():
    """Crossing 10k monthly contracts caps premium>=0.05 at 0.50 (was 0.65)."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # premium 0.10, cumulative 12000 -> 0.50/contract, 10 contracts -> 5.00; min 1.00 -> 5.00
    commission = model._option_commission(
        Decimal("10"),
        Decimal("0.10"),
        first_fill=True,
        cumulative_monthly_contracts=Decimal("12000"),
    )
    assert commission == Decimal("5.00")


def test_option_tiered_high_volume_override():
    """150k monthly contracts lands in the all-premiums-0.15 tier."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    # premium 0.10, cumulative 150000 -> 0.15/contract, 100 contracts -> 15.00
    commission = model._option_commission(
        Decimal("100"),
        Decimal("0.10"),
        first_fill=True,
        cumulative_monthly_contracts=Decimal("150000"),
    )
    assert commission == Decimal("15.00")


def test_option_monthly_contracts_override_skips_state():
    """A pinned monthly_contracts resolves the rate without accumulating internal state."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered", monthly_contracts=Decimal("12000")))
    order = _OrderStub(filled_qty=0)
    cumulative = model._cumulative_monthly_contracts(order, Decimal("10"))
    assert cumulative == Decimal("12000")
    assert model._monthly_contracts == {}


def test_option_monthly_accumulation_across_fills():
    """Accumulating option fills within a month crosses 10k and lowers the rate."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    order_ts = _ns(2024, 1)
    # First fill: cumulative becomes 10000 -> still <=10k tier, premium 0.10 -> 0.65.
    cum1 = model._cumulative_monthly_contracts(_OrderStub(filled_qty=0, ts_init=order_ts), Decimal("10000"))
    assert cum1 == Decimal("10000")
    assert option_tiered_per_contract(Decimal("0.10"), cum1) == Decimal("0.65")
    # Next fill pushes cumulative to 10001 -> 10k-50k tier, premium 0.10 -> 0.50.
    cum2 = model._cumulative_monthly_contracts(_OrderStub(filled_qty=0, ts_init=order_ts), Decimal("1"))
    assert cum2 == Decimal("10001")
    assert option_tiered_per_contract(Decimal("0.10"), cum2) == Decimal("0.50")


def test_option_monthly_accumulation_separate_months():
    """Option contract volume is bucketed per calendar month."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    jan = model._cumulative_monthly_contracts(_OrderStub(filled_qty=0, ts_init=_ns(2024, 1)), Decimal("10000"))
    feb = model._cumulative_monthly_contracts(_OrderStub(filled_qty=0, ts_init=_ns(2024, 2)), Decimal("1"))
    assert jan == Decimal("10000")
    assert feb == Decimal("1")  # February starts fresh, not 10001.


def test_reset_clears_both_states():
    """reset() zeroes both share and contract accumulators."""
    model = IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered"))
    model._cumulative_monthly_shares(_OrderStub(filled_qty=0), Decimal("1000"))
    model._cumulative_monthly_contracts(_OrderStub(filled_qty=0), Decimal("10"))
    assert model._monthly_shares != {}
    assert model._monthly_contracts != {}
    model.reset()
    assert model._monthly_shares == {}
    assert model._monthly_contracts == {}


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
    """Config defaults to tiered pricing with inferred asset class and no volume overrides."""
    config = IBKRFeeModelConfig()
    assert config.pricing == "tiered"
    assert config.asset_class is None
    assert config.monthly_volume is None
    assert config.monthly_contracts is None
