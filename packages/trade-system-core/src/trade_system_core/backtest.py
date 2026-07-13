"""Backtest runner wrapping :class:`~nautilus_trader.backtest.node.BacktestNode`.

Provides three levels of abstraction:

- :func:`run_backtest` — full control from a :class:`~trade_system_core.config.RunConfig`
- :func:`quick_backtest` — single-strategy shorthand
- :func:`grid_backtest` — Cartesian-product parameter sweep for optimisation

"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
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
        "OptionContract": "nautilus_trader.model.instruments:OptionContract",
        "Equity": "nautilus_trader.model.instruments:Equity",
        "FuturesContract": "nautilus_trader.model.instruments:FuturesContract",
    }
    raw_cls = dc.data_cls or "Bar"
    resolved_cls = _DATA_CLS_ALIASES.get(raw_cls, raw_cls)

    return BacktestDataConfig(
        catalog_path=dc.catalog_path or "",
        data_cls=resolved_cls,
        instrument_id=dc.instrument_id or None,
        instrument_ids=dc.instrument_ids,
        bar_spec=bar_spec,
        start_time=dc.start_time,
        end_time=dc.end_time,
    )


def _strategy_config_to_importable(sc: StrategyConfig, overrides: dict | None = None) -> ImportableStrategyConfig:
    """Convert a :class:`StrategyConfig` to an :class:`ImportableStrategyConfig`.

    *overrides* are merged on top of ``sc.config`` — used by grid backtest
    to inject parameter combinations.
    """
    merged = {**sc.config, **(overrides or {})}
    return ImportableStrategyConfig(
        strategy_path=sc.strategy_path,
        config_path=sc.config_path,
        config=merged,
    )


# ── Grid result ─────────────────────────────────────────────────────────


@dataclass
class GridBacktestResult:
    """A single row in a matrix backtest result table.

    Attributes:
        params: The parameter combination used for this run.
        result: The NautilusTrader :class:`~nautilus_trader.backtest.results.BacktestResult`.
        total_pnl: Total realised + unrealised PnL.
        sharpe_ratio: Annualised Sharpe ratio (``None`` when not computable).
        max_drawdown: Maximum drawdown as a positive ``Decimal``.
        total_trades: Number of closed trades.

    """

    params: dict
    result: BacktestResult
    total_pnl: Decimal = Decimal("0")
    sharpe_ratio: float | None = None
    max_drawdown: Decimal = Decimal("0")
    total_trades: int = 0


# ── Public API ──────────────────────────────────────────────────────────


_DEFAULT_OUTPUT_DIR = Path(".tmp")


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    """Resolve and create the output directory for HTML reports.

    Parameters
    ----------
    output_dir : str or Path or None
        Explicit output directory.  When ``None``, defaults to ``.tmp``.

    Returns:
    -------
    Path
        The resolved (and created) output directory.

    """
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


def quick_backtest(
    *,
    strategy_path: str,
    config_path: str,
    strategy_config: dict,
    instrument_id: str,
    bar_type: str,
    catalog_path: str,
    start_time: str,
    end_time: str,
    starting_balances: list[str] = ["100_000 USD"],  # noqa: B006
    fee_model: str | None = None,
    fill_model: dict | None = None,
    latency_model: dict | None = None,
    tearsheet: bool = False,
    output_dir: str | Path | None = None,
    extra_data: list[DataConfig] | None = None,
) -> BacktestResult:
    """Run a single-strategy backtest with minimal boilerplate.

    Parameters
    ----------
    strategy_path : str
        Dotted path to the strategy class (e.g.
        ``"trade_system_strategies.rsi.strategy:RsiStrategy"``).
    config_path : str
        Dotted path to the config class.
    strategy_config : dict
        Strategy-specific parameters.
    instrument_id : str
        Instrument identifier (e.g. ``"SPY.ARCX"``).
    bar_type : str
        Bar type string (e.g. ``"SPY.ARCX-1-MINUTE-LAST-EXTERNAL"``).
    catalog_path : str
        Path to the ParquetDataCatalog.
    start_time : str
        ISO-8601 start timestamp.
    end_time : str
        ISO-8601 end timestamp.
    starting_balances : list[str], optional
        Starting balance strings.
    fee_model : str or None, optional
        Registry key for the fee model (e.g. ``"ibkr_tiered"``).
    fill_model : dict or None, optional
        Fill / slippage model config dict with keys ``fill_model_path``,
        ``config_path``, ``config``.  E.g.
        ``{"fill_model_path": "nautilus_trader.backtest.models.fill:OneTickSlippageFillModel"}``.
    latency_model : dict or None, optional
        Latency model config dict with keys ``latency_model_path``,
        ``config_path``, ``config``.
    tearsheet : bool, optional
        If ``True``, generate an HTML tearsheet.
    output_dir : str or Path or None, optional
        Directory for HTML tearsheet output.  Defaults to ``.tmp``.
    extra_data : list[DataConfig] or None, optional
        Additional data configurations appended to the primary bar data
        (e.g. option instruments for multi-asset strategies).

    Returns:
    -------
    BacktestResult

    """
    data_list: list[DataConfig] = [
        DataConfig(
            catalog_path=catalog_path,
            instrument_id=instrument_id,
            bar_type=bar_type,
            start_time=start_time,
            end_time=end_time,
        )
    ]
    if extra_data:
        data_list.extend(extra_data)

    run_config = RunConfig(
        mode="backtest",
        trader_id="QUICK-BT-001",
        venues=[
            VenueConfig(
                name=instrument_id.split(".")[-1],
                starting_balances=starting_balances,
                fee_model=fee_model,
                fill_model=fill_model,
                latency_model=latency_model,
            ),
        ],
        data=data_list,
        strategies=[StrategyConfig(strategy_path=strategy_path, config_path=config_path, config=strategy_config)],
    )
    results = run_backtest(run_config, tearsheet=tearsheet, output_dir=output_dir)
    return results[0]


def grid_backtest(
    *,
    strategy_path: str,
    config_path: str,
    base_config: dict,
    param_grid: dict[str, list],
    instrument_id: str,
    bar_type: str,
    catalog_path: str,
    start_time: str,
    end_time: str,
    starting_balances: list[str] = ["100_000 USD"],  # noqa: B006
    fee_model: str | None = None,
    fill_model: dict | None = None,
    latency_model: dict | None = None,
) -> list[GridBacktestResult]:
    """Run a Cartesian-product parameter sweep across *param_grid*.

    Each key in *param_grid* maps to a list of candidate values.  The
    runner computes the Cartesian product, creates one :class:`BacktestRunConfig`
    per combination, and returns all results sorted by ``total_pnl`` descending.

    Parameters
    ----------
    strategy_path : str
        Dotted path to the strategy class.
    config_path : str
        Dotted path to the config class.
    base_config : dict
        Base strategy parameters (shared across all combinations).
    param_grid : dict[str, list]
        Parameter names → candidate value lists.
    instrument_id : str
        Instrument identifier.
    bar_type : str
        Bar type string.
    catalog_path : str
        Path to the ParquetDataCatalog.
    start_time : str
        ISO-8601 start timestamp.
    end_time : str
        ISO-8601 end timestamp.
    starting_balances : list[str], optional
        Starting balance strings.
    fee_model : str or None, optional
        Registry key for the fee model.
    fill_model : dict or None, optional
        Fill / slippage model config dict.
    latency_model : dict or None, optional
        Latency model config dict.

    Returns:
    -------
    list[GridBacktestResult]
        Sorted by ``total_pnl`` descending.

    """
    # Expand parameter grid into list of override dicts
    keys = list(param_grid)
    value_lists = [param_grid[k] for k in keys]
    combos: list[dict] = [dict(zip(keys, vals)) for vals in itertools.product(*value_lists)]  # noqa: B905

    venue_name = instrument_id.split(".")[-1]
    data_cfg = DataConfig(
        catalog_path=catalog_path,
        instrument_id=instrument_id,
        bar_type=bar_type,
        start_time=start_time,
        end_time=end_time,
    )
    venue_cfg = VenueConfig(
        name=venue_name,
        starting_balances=starting_balances,
        fee_model=fee_model,
        fill_model=fill_model,
        latency_model=latency_model,
    )

    run_configs: list[BacktestRunConfig] = []
    for combo in combos:
        merged_config = {**base_config, **combo}
        sc = StrategyConfig(
            strategy_path=strategy_path,
            config_path=config_path,
            config=merged_config,
        )
        run_configs.append(
            BacktestRunConfig(
                engine=BacktestEngineConfig(
                    trader_id=TraderId("GRID-BT-001"),
                    strategies=[_strategy_config_to_importable(sc)],
                    run_analysis=True,
                ),
                venues=[_venue_config_to_backtest(venue_cfg)],
                data=[_data_config_to_backtest(data_cfg)],
                dispose_on_completion=False,
            ),
        )

    node = BacktestNode(run_configs)
    raw_results = node.run()

    # Wrap each raw result with extracted metrics
    grid_results: list[GridBacktestResult] = []
    for combo, raw in zip(combos, raw_results):  # noqa: B905
        total_pnl = Decimal("0")
        max_dd = Decimal("0")
        trades = 0
        for currency, stats in raw.stats_pnls.items():  # noqa: B007
            total_pnl += Decimal(str(stats.total_pnl)) if hasattr(stats, "total_pnl") else Decimal("0")
            max_dd = max(max_dd, Decimal(str(stats.max_drawdown)) if hasattr(stats, "max_drawdown") else Decimal("0"))
            trades += stats.total_trades if hasattr(stats, "total_trades") else 0

        grid_results.append(
            GridBacktestResult(
                params=combo,
                result=raw,
                total_pnl=total_pnl,
                max_drawdown=max_dd,
                total_trades=trades,
            ),
        )

    grid_results.sort(key=lambda r: r.total_pnl, reverse=True)
    return grid_results
