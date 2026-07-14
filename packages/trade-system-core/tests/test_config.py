"""Tests for trade_system_core.config."""

from __future__ import annotations

import tempfile

from trade_system_core.config import DataConfig
from trade_system_core.config import StrategyConfig
from trade_system_core.config import VenueConfig
from trade_system_core.config import load_config


class TestVenueConfig:
    """Tests for VenueConfig defaults and field handling."""

    def test_defaults(self):  # noqa: D102
        vc = VenueConfig()
        assert vc.name == "SIM"
        assert vc.oms_type == "NETTING"
        assert vc.account_type == "MARGIN"
        assert vc.base_currency == "USD"
        assert vc.starting_balances == ["100_000 USD"]
        assert vc.fee_model is None
        assert vc.fill_model is None
        assert vc.latency_model is None
        assert vc.exec_client is None

    def test_custom_values(self):  # noqa: D102
        vc = VenueConfig(
            name="ARCA",
            oms_type="HEDGING",
            account_type="CASH",
            starting_balances=["50_000 USD"],
            fee_model="ibkr_tiered",
            fill_model={"fill_model_path": "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel"},
            exec_client="IBKR",
        )
        assert vc.name == "ARCA"
        assert vc.fee_model == "ibkr_tiered"
        assert vc.fill_model["fill_model_path"] == "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel"
        assert vc.exec_client == "IBKR"


class TestDataConfig:
    """Tests for DataConfig defaults."""

    def test_defaults(self):  # noqa: D102
        dc = DataConfig()
        assert dc.catalog_path is None
        assert dc.instrument_id == ""
        assert dc.data_client is None

    def test_custom(self):  # noqa: D102
        dc = DataConfig(
            catalog_path="/data/catalog",
            instrument_id="SPY.ARCA",
            bar_type="SPY.ARCA-1-MINUTE-LAST-EXTERNAL",
            data_client="MASSIVE",
        )
        assert dc.catalog_path == "/data/catalog"
        assert dc.data_client == "MASSIVE"


class TestStrategyConfig:
    """Tests for StrategyConfig."""

    def test_basic(self):  # noqa: D102
        sc = StrategyConfig(
            strategy_path="foo:Bar",
            config_path="foo:Baz",
            config={"x": 1},
        )
        assert sc.config == {"x": 1}


class TestLoadConfig:
    """Tests for YAML config loading."""

    def test_minimal_yaml(self):  # noqa: D102
        yaml_content = """
mode: backtest
trader_id: "TEST-001"
venues:
  - name: SIM
data: []
strategies: []
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            f.flush()
            config = load_config(f.name)

        assert config.mode == "backtest"
        assert config.trader_id == "TEST-001"
        assert len(config.venues) == 1
        assert config.venues[0].name == "SIM"

    def test_full_yaml(self):  # noqa: D102
        yaml_content = """
mode: live
trader_id: "RSI-LIVE-001"
venues:
  - name: BINANCE
    oms_type: NETTING
    account_type: MARGIN
    starting_balances: ["10_000 USD"]
    fee_model: binance_spot
    exec_client: BINANCE
data_clients:
  MASSIVE:
    api_key: null
exec_clients:
  BINANCE:
    api_key: null
data:
  - instrument_id: "BTC/USDT.BINANCE"
    bar_type: "BTC/USDT.BINANCE-1-HOUR-LAST-EXTERNAL"
    data_client: MASSIVE
strategies:
  - strategy_path: "trade_system_strategies.rsi.strategy:RsiStrategy"
    config_path: "trade_system_strategies.rsi.config:RsiConfig"
    config:
      instrument_id: "BTC/USDT.BINANCE"
observability:
  enabled: true
  otlp_endpoint: "http://otel-collector:4317"
dry_run: true
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            f.flush()
            config = load_config(f.name)

        assert config.mode == "live"
        assert config.dry_run is True
        assert config.venues[0].fee_model == "binance_spot"
        assert config.venues[0].exec_client == "BINANCE"
        assert config.data[0].data_client == "MASSIVE"
        assert "MASSIVE" in config.data_clients
        assert config.observability.otlp_endpoint == "http://otel-collector:4317"

    def test_fill_model_in_yaml(self):  # noqa: D102
        yaml_content = """
mode: backtest
venues:
  - name: ARCA
    fill_model:
      fill_model_path: "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel"
      config_path: ""
      config: {}
data: []
strategies: []
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            f.flush()
            config = load_config(f.name)

        assert config.venues[0].fill_model is not None
        assert "OneTickSlippageFillModel" in config.venues[0].fill_model["fill_model_path"]

    def test_empty_yaml(self):  # noqa: D102
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("")
            f.flush()
            config = load_config(f.name)

        # All defaults
        assert config.mode == "backtest"
        assert config.trader_id == "TRADER-001"
