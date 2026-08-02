"""Verify 0DTE iron condor public API imports work end-to-end."""

from options_strategies.odte_iron_condor import OdteIronCondorConfig
from options_strategies.odte_iron_condor import odte_entry_dates
from options_strategies.odte_iron_condor import run_odte_iron_condor
from options_strategies.odte_iron_condor.config import OdteIronCondorConfig as ConfigDirect
from options_strategies.odte_iron_condor.signals import odte_entry_dates as entry_direct
from options_strategies.odte_iron_condor.strategy import run_odte_iron_condor as run_direct


def test_odte_config_defaults() -> None:
    """OdteIronCondorConfig can be instantiated with only required defaults."""
    config = OdteIronCondorConfig(symbol="SPY", capital=100_000.0)
    assert config.symbol == "SPY"
    assert config.capital == 100_000.0
    assert config.symbols == ["SPY"]
    assert config.take_profit == 0.5
    assert config.stop_loss == -2.0
    assert config.short_put_delta == 0.30
    assert config.long_put_delta == 0.10
    assert config.max_entry_dte == 1
    assert config.exit_dte == 0


def test_odte_config_custom() -> None:
    """OdteIronCondorConfig accepts custom delta and risk parameters."""
    config = OdteIronCondorConfig(
        symbol="SPY",
        capital=50_000.0,
        symbols=["SPY", "QQQ", "IWM"],
        short_put_delta=0.25,
        short_call_delta=0.25,
        long_put_delta=0.05,
        long_call_delta=0.05,
        take_profit=0.5,
        stop_loss=-2.0,
    )
    assert config.symbols == ["SPY", "QQQ", "IWM"]
    assert config.short_put_delta == 0.25
    assert config.long_put_delta == 0.05


def test_odte_config_frozen() -> None:
    """OdteIronCondorConfig is frozen (immutable)."""
    config = OdteIronCondorConfig()
    try:
        config.capital = 999  # type: ignore[misc]
    except Exception:
        pass
    else:
        msg = "Frozen config should reject attribute assignment"
        raise AssertionError(msg)


def test_api_aliases_match() -> None:
    """Top-level re-exports point to the same objects as the submodules."""
    assert OdteIronCondorConfig is ConfigDirect
    assert run_odte_iron_condor is run_direct
    assert odte_entry_dates is entry_direct
