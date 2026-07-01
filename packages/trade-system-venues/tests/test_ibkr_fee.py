"""Scaffold smoke tests for the IBKR fee model."""

from nautilus_trader.backtest.models import FeeModel

from trade_system_venues.ibkr.fee import IBKRFeeModel
from trade_system_venues.ibkr.fee import IBKRFeeModelConfig


def test_ibkr_fee_model_is_fee_model():
    """IBKRFeeModel subclasses the NautilusTrader FeeModel base."""
    assert issubclass(IBKRFeeModel, FeeModel)


def test_ibkr_fee_model_config_defaults():
    """Config defaults to tiered pricing with inferred asset class."""
    config = IBKRFeeModelConfig()
    assert config.pricing == "tiered"
    assert config.asset_class is None


def test_ibkr_fee_model_instantiates_with_default_config():
    """The model can be constructed without an explicit config."""
    assert IBKRFeeModel() is not None
