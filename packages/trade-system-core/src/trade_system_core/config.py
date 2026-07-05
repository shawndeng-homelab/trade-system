"""YAML-driven run configuration for backtest and live trading.

Loads a single YAML file into a :class:`RunConfig` struct that the runner
modules (:mod:`~trade_system_core.backtest`, :mod:`~trade_system_core.live`)
consume to build NautilusTrader nodes.

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import msgspec
import yaml


# ── Configuration structs ──────────────────────────────────────────────


class VenueConfig(msgspec.Struct, frozen=True):
    """Configuration for a simulated or live trading venue.

    Attributes:
        name: Venue identifier (e.g. ``"ARCA"``, ``"BINANCE"``).
        oms_type: Order management system type (``"NETTING"`` or ``"HEDGING"``).
        account_type: Account type (``"MARGIN"``, ``"CASH"``).
        base_currency: Base currency code.
        starting_balances: Starting balance strings, e.g. ``["100_000 USD"]``.
        fee_model: Registry key for the fee model (e.g. ``"ibkr_tiered"``).
        fill_model: Fill / slippage model configuration dict with keys
            ``fill_model_path``, ``config_path``, ``config``.  Maps to
            NautilusTrader's ``ImportableFillModelConfig``.  Built-in options
            include ``BestPriceFillModel`` (no slippage),
            ``OneTickSlippageFillModel`` (1-tick slip), and
            ``ProbabilisticFillModel`` (probabilistic fills + slippage).
        latency_model: Latency model configuration dict with keys
            ``latency_model_path``, ``config_path``, ``config``.  Maps to
            NautilusTrader's ``ImportableLatencyModelConfig``.
        exec_client: Registry key for the live exec client (e.g. ``"IBKR"``).

    """

    name: str = "SIM"
    oms_type: str = "NETTING"
    account_type: str = "MARGIN"
    base_currency: str = "USD"
    starting_balances: list[str] = msgspec.field(default_factory=lambda: ["100_000 USD"])
    fee_model: str | None = None
    fill_model: dict[str, Any] | None = None
    latency_model: dict[str, Any] | None = None
    exec_client: str | None = None


class DataConfig(msgspec.Struct, frozen=True):
    """Configuration for a data source (historical or live).

    Attributes:
        catalog_path: Path to the :class:`~nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog`.
        instrument_id: Instrument identifier (e.g. ``"SPY.ARCA"``).
        bar_type: Bar type string (e.g. ``"SPY.ARCA-1-MINUTE-LAST-EXTERNAL"``).
        start_time: ISO-8601 start timestamp for backtest data.
        end_time: ISO-8601 end timestamp for backtest data.
        data_client: Registry key for the live data client (e.g. ``"MASSIVE"``).

    """

    catalog_path: str | None = None
    instrument_id: str = ""
    bar_type: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    data_client: str | None = None


class StrategyConfig(msgspec.Struct, frozen=True):
    """Configuration for a trading strategy.

    Attributes:
        strategy_path: Dotted path to the strategy class
            (e.g. ``"trade_system_strategies.rsi.strategy:RsiStrategy"``).
        config_path: Dotted path to the config class
            (e.g. ``"trade_system_strategies.rsi.config:RsiConfig"``).
        config: Strategy-specific parameters.
        param_grid: Parameter grid for matrix backtesting.  Keys are strategy
            config field names; values are lists of candidate values.  The
            runner computes the Cartesian product and runs one backtest per
            combination.

    """

    strategy_path: str = ""
    config_path: str = ""
    config: dict[str, Any] = msgspec.field(default_factory=dict)
    param_grid: dict[str, list] | None = None


class ObservabilityConfig(msgspec.Struct, frozen=True):
    """Configuration for OpenTelemetry observability.

    Attributes:
        enabled: Whether to initialize OTel instrumentation.
        service_name: Service name for OTel resource.
        otlp_endpoint: OTLP gRPC endpoint (e.g. ``"http://localhost:4317"``).
        export_interval_ms: Metric export interval in milliseconds.

    """

    enabled: bool = True
    service_name: str = "trade-system"
    otlp_endpoint: str = "http://localhost:4317"
    export_interval_ms: int = 5000


class RunConfig(msgspec.Struct, frozen=True):
    """Top-level configuration loaded from a YAML file.

    Attributes:
        mode: Execution mode — ``"backtest"`` or ``"live"``.
        trader_id: Trader identifier string.
        venues: Venue configurations.
        data: Data source configurations.
        strategies: Strategy configurations.
        observability: OTel configuration.
        data_clients: Live data client configs keyed by adapter name.
        exec_clients: Live exec client configs keyed by adapter name.
        dry_run: If ``True`` in live mode, use SIM execution instead of real.

    """

    mode: str = "backtest"
    trader_id: str = "TRADER-001"
    venues: list[VenueConfig] = msgspec.field(default_factory=list)
    data: list[DataConfig] = msgspec.field(default_factory=list)
    strategies: list[StrategyConfig] = msgspec.field(default_factory=list)
    observability: ObservabilityConfig = ObservabilityConfig()
    data_clients: dict[str, dict[str, Any]] = msgspec.field(default_factory=dict)
    exec_clients: dict[str, dict[str, Any]] = msgspec.field(default_factory=dict)
    dry_run: bool = False


# ── Loader ─────────────────────────────────────────────────────────────


def load_config(path: str | Path) -> RunConfig:
    """Load a YAML configuration file and return a :class:`RunConfig`.

    Parameters
    ----------
    path : str or Path
        Path to the YAML configuration file.

    Returns:
    -------
    RunConfig

    """
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        data = {}
    return msgspec.convert(data, RunConfig)
