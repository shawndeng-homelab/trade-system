"""Verify iron condor public API imports work end-to-end."""

import pandas as pd
import pytest
from options_strategies.odte_iron_condor import OdteIronCondorConfig
from options_strategies.odte_iron_condor import odte_entry_dates
from options_strategies.odte_iron_condor import run_odte_iron_condor
from options_strategies.odte_iron_condor.config import OdteIronCondorConfig as ConfigDirect
from options_strategies.odte_iron_condor.signals import odte_entry_dates as entry_direct
from options_strategies.odte_iron_condor.strategy import run_odte_iron_condor as run_direct
from pydantic import ValidationError


def test_odte_config_defaults() -> None:
    """OdteIronCondorConfig can be instantiated with only required defaults."""
    config = OdteIronCondorConfig(symbol="SPY", capital=100_000.0)
    assert config.symbol == "SPY"
    assert config.capital == 100_000.0
    assert config.symbols == ["SPY"]
    assert config.entry_cycle == "daily"
    assert config.take_profit == 0.5
    assert config.stop_loss == -2.0
    assert config.short_put_delta == 0.30
    assert config.long_put_delta == 0.10
    assert config.max_entry_dte == 3
    assert config.exit_dte == 0
    assert config.exit_dte_tolerance == 1


def test_odte_config_custom() -> None:
    """OdteIronCondorConfig accepts custom delta and risk parameters."""
    config = OdteIronCondorConfig(
        symbol="SPY",
        capital=50_000.0,
        symbols=["SPY", "QQQ", "IWM"],
        entry_cycle="biweekly",
        short_put_delta=0.25,
        short_call_delta=0.25,
        long_put_delta=0.05,
        long_call_delta=0.05,
        max_entry_dte=14,
        exit_dte=7,
        exit_dte_tolerance=1,
        take_profit=0.5,
        stop_loss=-2.0,
    )
    assert config.symbols == ["SPY", "QQQ", "IWM"]
    assert config.entry_cycle == "biweekly"
    assert config.short_put_delta == 0.25
    assert config.long_put_delta == 0.05
    assert config.max_entry_dte == 14
    assert config.exit_dte == 7


def test_odte_config_entry_cycle_validation() -> None:
    """OdteIronCondorConfig rejects invalid entry_cycle values."""
    with pytest.raises(ValidationError):
        OdteIronCondorConfig(entry_cycle="quarterly")


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


def _synthetic_stock() -> pd.DataFrame:
    """Build a minimal stock OHLCV DataFrame for signal tests."""
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    return pd.DataFrame(
        {
            "underlying_symbol": "TEST",
            "quote_date": dates,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
    )


def test_entry_dates_daily() -> None:
    """Daily cycle produces one entry per trading day."""
    stock = _synthetic_stock()
    result = odte_entry_dates(stock, entry_cycle="daily")
    assert len(result) == 60
    assert list(result.columns) == ["underlying_symbol", "quote_date"]


def test_entry_dates_weekly() -> None:
    """Weekly cycle produces fewer entries than daily."""
    stock = _synthetic_stock()
    daily = odte_entry_dates(stock, entry_cycle="daily")
    weekly = odte_entry_dates(stock, entry_cycle="weekly")
    assert len(weekly) < len(daily)
    assert len(weekly) > 0


def test_entry_dates_biweekly() -> None:
    """Biweekly cycle produces roughly half as many entries as weekly."""
    stock = _synthetic_stock()
    weekly = odte_entry_dates(stock, entry_cycle="weekly")
    biweekly = odte_entry_dates(stock, entry_cycle="biweekly")
    assert len(biweekly) <= len(weekly)
    assert len(biweekly) > 0


def test_entry_dates_monthly() -> None:
    """Monthly cycle produces one entry per calendar month."""
    stock = _synthetic_stock()
    monthly = odte_entry_dates(stock, entry_cycle="monthly")
    # 60 business days starting 2024-01-01 spans ~3 months
    assert len(monthly) == 3


def test_entry_dates_invalid_cycle() -> None:
    """Invalid entry_cycle raises ValueError."""
    stock = _synthetic_stock()
    with pytest.raises(ValueError, match="Unknown entry_cycle"):
        odte_entry_dates(stock, entry_cycle="quarterly")
