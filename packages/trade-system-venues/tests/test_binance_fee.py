"""Scaffold smoke tests for the Binance fee model."""

from nautilus_trader.backtest.models import FeeModel

from trade_system_venues.binance.fee import BinanceFeeModel
from trade_system_venues.binance.fee import BinanceFeeModelConfig


def test_binance_fee_model_is_fee_model():
    """BinanceFeeModel subclasses the NautilusTrader FeeModel base."""
    assert issubclass(BinanceFeeModel, FeeModel)


def test_binance_fee_model_config_defaults():
    """Config exposes the expected Binance-specific defaults."""
    config = BinanceFeeModelConfig()
    assert config.account_type == "usdt_futures"
    assert config.vip_level == 0
    assert config.use_bnb_discount is False


def test_binance_fee_model_instantiates_with_default_config():
    """The model can be constructed without an explicit config."""
    assert BinanceFeeModel() is not None
