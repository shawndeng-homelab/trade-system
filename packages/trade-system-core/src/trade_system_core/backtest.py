"""Backtest runner wrapping :class:`~nautilus_trader.backtest.node.BacktestNode`.

Provides:

- :func:`run_backtest` — full control from a :class:`~trade_system_core.config.RunConfig`

For simple single-strategy backtests or multi-venue setups, use NautilusTrader's
:class:`~nautilus_trader.backtest.engine.BacktestEngine` directly — see
``scripts/backtest_rsi.py`` and ``scripts/backtest_pmcc.py`` for examples.
"""

from __future__ import annotations

import os
from pathlib import Path

from nautilus_trader.analysis.tearsheet import create_tearsheet
from nautilus_trader.backtest.config import BacktestDataConfig
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.config import BacktestRunConfig
from nautilus_trader.backtest.config import BacktestVenueConfig
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.backtest.results import BacktestResult
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import TraderId

from trade_system_core.config import DataConfig
from trade_system_core.config import RunConfig
from trade_system_core.config import StrategyConfig
from trade_system_core.config import VenueConfig
from trade_system_core.registry import get_registry


# ── Helpers ─────────────────────────────────────────────────────────────


def _venue_config_to_backtest(vc: VenueConfig) -> BacktestVenueConfig:
    """Convert a :class:`VenueConfig` into a NautilusTrader :class:`BacktestVenueConfig`."""
    fee_model_path: str | None = None
    if vc.fee_model is not None:
        registry = get_registry()
        model_cls = registry.get_fee_model(vc.fee_model)
        # NautilusTrader supports ImportableFeeModelConfig with dotted path
        fee_model_path = f"{model_cls.__module__}:{model_cls.__name__}"

    # Build ImportableFillModelConfig from dict if provided
    fill_model_config = None
    if vc.fill_model is not None:
        from nautilus_trader.backtest.config import ImportableFillModelConfig  # noqa: PLC0415

        fill_model_config = ImportableFillModelConfig(
            fill_model_path=vc.fill_model["fill_model_path"],
            config_path=vc.fill_model.get("config_path", ""),
            config=vc.fill_model.get("config", {}),
        )

    # Build ImportableLatencyModelConfig from dict if provided
    latency_model_config = None
    if vc.latency_model is not None:
        from nautilus_trader.backtest.config import ImportableLatencyModelConfig  # noqa: PLC0415

        latency_model_config = ImportableLatencyModelConfig(
            latency_model_path=vc.latency_model["latency_model_path"],
            config_path=vc.latency_model.get("config_path", ""),
            config=vc.latency_model.get("config", {}),
        )

    return BacktestVenueConfig(
        name=vc.name,
        oms_type=OmsType[vc.oms_type],
        account_type=AccountType[vc.account_type],
        base_currency=vc.base_currency if vc.base_currency else None,
        starting_balances=vc.starting_balances,
        fee_model=fee_model_path,
        fill_model=fill_model_config,
        latency_model=latency_model_config,
        book_type="L1_MBP",
    )


def _data_config_to_backtest(dc: DataConfig) -> BacktestDataConfig:
    """Convert a :class:`DataConfig` into a NautilusTrader :class:`BacktestDataConfig`."""
    # bar_type format: "INSTRUMENT_ID-step-AGG-PRICE-AGGSRC"
    #   e.g. "SPY.ARCX-1-HOUR-LAST-EXTERNAL"
    # NautilusTrader's bar_spec is just "step-AGG": "1-HOUR"
    bar_spec = None
    if dc.bar_type:
        # Strip instrument_id prefix (everything before first "-")
        spec_part = dc.bar_type.split("-", maxsplit=1)[1]  # "1-HOUR-LAST-EXTERNAL"
        # Take only the first two components: step + aggregation
        parts = spec_part.split("-")
        if len(parts) >= 2:
            bar_spec = f"{parts[0]}-{parts[1]}"  # "1-HOUR"

    # NautilusTrader's BacktestDataConfig.data_cls requires a dotted "module:ClassName"
    # path that resolve_path() can parse.  Accept either a short name (e.g. "Bar",
    # "OptionContract") or a full path (e.g. "nautilus_trader.model.data:Bar").
    _DATA_CLS_ALIASES: dict[str, str] = {
        "Bar": "nautilus_trader.model.data:Bar",
        "TradeTick": "nautilus_trader.model.data:TradeTick",
        "QuoteTick": "nautilus_trader.model.data:QuoteTick",
    }
    raw_cls = dc.data_cls or "Bar"
    resolved_cls = _DATA_CLS_ALIASES.get(raw_cls, raw_cls)

    return BacktestDataConfig(
        catalog_path=dc.catalog_path or os.environ.get("NAUTILUS_PATH", ""),
        data_cls=resolved_cls,
        instrument_id=dc.instrument_id or None,
        instrument_ids=dc.instrument_ids,
        bar_spec=bar_spec,
        start_time=dc.start_time,
        end_time=dc.end_time,
    )


def _strategy_config_to_importable(sc: StrategyConfig, overrides: dict | None = None) -> ImportableStrategyConfig:
    """Convert a :class:`StrategyConfig` to an :class:`ImportableStrategyConfig`.

    *overrides* are merged on top of ``sc.config``.
    """
    merged = {**sc.config, **(overrides or {})}
    return ImportableStrategyConfig(
        strategy_path=sc.strategy_path,
        config_path=sc.config_path,
        config=merged,
    )


# ── Public API ──────────────────────────────────────────────────────────


_DEFAULT_OUTPUT_DIR = Path(".tmp")


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    """Resolve and create the output directory for HTML reports."""
    dir_path = Path(output_dir) if output_dir is not None else _DEFAULT_OUTPUT_DIR
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def run_backtest(
    config: RunConfig,
    *,
    tearsheet: bool = False,
    output_dir: str | Path | None = None,
) -> list[BacktestResult]:
    """Execute a backtest from a :class:`RunConfig`.

    Parameters
    ----------
    config : RunConfig
        The loaded YAML configuration.
    tearsheet : bool, optional
        If ``True``, generate an interactive HTML tearsheet for each result.
    output_dir : str or Path or None, optional
        Directory for HTML tearsheet output.  Defaults to ``.tmp``.

    Returns:
    -------
    list[BacktestResult]

    """
    run_configs: list[BacktestRunConfig] = []

    for sc in config.strategies:
        run_configs.append(
            BacktestRunConfig(
                engine=BacktestEngineConfig(
                    trader_id=TraderId(config.trader_id),
                    strategies=[_strategy_config_to_importable(sc)],
                    run_analysis=True,
                ),
                venues=[_venue_config_to_backtest(vc) for vc in config.venues],
                data=[_data_config_to_backtest(dc) for dc in config.data],
                dispose_on_completion=False,
            ),
        )

    node = BacktestNode(run_configs)
    results = node.run()

    if tearsheet:
        out = _resolve_output_dir(output_dir)
        engines = node.get_engines()
        for idx, engine in enumerate(engines):
            path = str(out / f"tearsheet_{idx}.html")
            title = f"Backtest {idx}"
            create_tearsheet(engine, output_path=path, title=title)

    return results
