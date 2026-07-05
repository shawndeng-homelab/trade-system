"""Tests for trade_system_core.backtest — configuration conversion logic."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from trade_system_core.backtest import _data_config_to_backtest
from trade_system_core.backtest import _strategy_config_to_importable
from trade_system_core.backtest import _venue_config_to_backtest
from trade_system_core.config import DataConfig
from trade_system_core.config import StrategyConfig
from trade_system_core.config import VenueConfig


class TestVenueConfigToBacktest:
    """Tests for _venue_config_to_backtest conversion."""

    def test_basic_conversion(self):  # noqa: D102
        vc = VenueConfig(name="ARCA", oms_type="NETTING", account_type="MARGIN", starting_balances=["10_000 USD"])
        result = _venue_config_to_backtest(vc)
        assert result.name == "ARCA"

    def test_with_fee_model(self):  # noqa: D102
        vc = VenueConfig(name="ARCA", fee_model="ibkr_tiered")

        # Mock the registry to avoid needing real fee model import
        mock_cls = MagicMock()
        mock_cls.__module__ = "fake.module"
        mock_cls.__name__ = "FakeModel"

        with patch("trade_system_core.backtest.get_registry") as mock_registry:
            mock_registry.return_value.get_fee_model.return_value = mock_cls
            result = _venue_config_to_backtest(vc)
            # Should produce dotted path string
            assert result.fee_model is not None
            assert "FakeModel" in result.fee_model

    def test_with_fill_model(self):  # noqa: D102
        vc = VenueConfig(
            name="ARCA",
            fill_model={
                "fill_model_path": "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel",
                "config_path": "",
                "config": {},
            },
        )
        result = _venue_config_to_backtest(vc)
        assert result.fill_model is not None
        assert result.fill_model.fill_model_path == "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel"

    def test_with_latency_model(self):  # noqa: D102
        vc = VenueConfig(
            name="ARCA",
            latency_model={
                "latency_model_path": "nautilus_trader.backtest.models.latency:LatencyModel",
                "config_path": "",
                "config": {"base_latency_nanos": 100},
            },
        )
        result = _venue_config_to_backtest(vc)
        assert result.latency_model is not None
        assert result.latency_model.latency_model_path == "nautilus_trader.backtest.models.latency:LatencyModel"


class TestDataConfigToBacktest:
    """Tests for _data_config_to_backtest conversion."""

    def test_basic_conversion(self):  # noqa: D102
        dc = DataConfig(
            catalog_path="/data/catalog",
            instrument_id="SPY.ARCA",
            bar_type="SPY.ARCA-1-MINUTE-LAST-EXTERNAL",
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-06-30T00:00:00+00:00",
        )
        result = _data_config_to_backtest(dc)
        assert result.instrument_id == "SPY.ARCA"


class TestStrategyConfigToImportable:
    """Tests for _strategy_config_to_importable conversion."""

    def test_basic(self):  # noqa: D102
        sc = StrategyConfig(
            strategy_path="foo:Bar",
            config_path="foo:Baz",
            config={"x": 1},
        )
        result = _strategy_config_to_importable(sc)
        assert result.strategy_path == "foo:Bar"
        assert result.config == {"x": 1}

    def test_overrides(self):  # noqa: D102
        sc = StrategyConfig(
            strategy_path="foo:Bar",
            config_path="foo:Baz",
            config={"x": 1, "y": 2},
        )
        result = _strategy_config_to_importable(sc, overrides={"y": 99, "z": 3})
        assert result.config == {"x": 1, "y": 99, "z": 3}
