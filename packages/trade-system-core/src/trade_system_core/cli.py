"""Click CLI entry point for trade-system.

Three commands:

- ``trade-system backtest <config.yaml>`` — run a backtest
- ``trade-system live <config.yaml>`` — run live trading
- ``trade-system run <config.yaml>`` — auto-detect mode from config

"""

from __future__ import annotations

from pathlib import Path

import click

from trade_system_core.config import load_config


@click.group()
def cli() -> None:
    """Trade system CLI — unified entry point for backtest, live, and parameter optimisation."""


@cli.command()
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.option("--tearsheet", is_flag=True, default=False, help="Generate an interactive HTML tearsheet.")
@click.option("--grid", is_flag=True, default=False, help="Enable matrix backtesting (requires param_grid in config).")
@click.option("--top-n", default=10, show_default=True, help="Show top N results in grid backtest.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose output.")
def backtest(config: Path, tearsheet: bool, grid: bool, top_n: int, verbose: bool) -> None:
    """Run a backtest from a YAML configuration file.

    If --grid is set and the config contains param_grid entries, a Cartesian-product
    parameter sweep is executed and results are sorted by total PnL.
    """
    from trade_system_core.adapters import get_registry  # noqa: F401, PLC0415

    run_config = load_config(config)

    # Initialize observability
    from trade_system_core.observability import init_observability  # noqa: PLC0415

    init_observability(run_config.observability)

    if verbose:
        click.echo(f"Loaded config: mode={run_config.mode}, trader_id={run_config.trader_id}")
        click.echo(f"  venues: {[v.name for v in run_config.venues]}")
        click.echo(f"  strategies: {[s.strategy_path for s in run_config.strategies]}")

    has_grid = any(s.param_grid for s in run_config.strategies)

    if grid and has_grid:
        _run_grid_backtest(run_config, top_n, verbose)
    else:
        _run_single_backtest(run_config, tearsheet, verbose)


def _run_single_backtest(run_config, tearsheet: bool, verbose: bool) -> None:
    """Execute a standard (non-grid) backtest."""
    from trade_system_core.backtest import run_backtest  # noqa: PLC0415

    results = run_backtest(run_config, tearsheet=tearsheet)

    for result in results:
        click.echo("\n========== Backtest Result ==========")
        click.echo(f"run_id:          {result.run_id}")
        click.echo(f"backtest range:  {result.backtest_start} -> {result.backtest_end}")
        click.echo(f"elapsed (s):     {result.elapsed_time:.2f}")
        click.echo(f"total events:    {result.total_events}")
        click.echo(f"total orders:    {result.total_orders}")
        click.echo(f"total positions: {result.total_positions}")

        click.echo("\n--- summary ---")
        for key, value in result.summary.items():
            click.echo(f"{key}: {value}")

        click.echo("\n--- PnL stats ---")
        for currency, stats in result.stats_pnls.items():
            click.echo(f"[{currency}] {stats}")

    if tearsheet:
        click.echo("\nTearsheet(s) written to: tearsheet_*.html")


def _run_grid_backtest(run_config, top_n: int, verbose: bool) -> None:
    """Execute a grid (matrix) backtest."""
    from trade_system_core.backtest import grid_backtest  # noqa: PLC0415

    # Collect grid params from the first strategy that has them
    for sc in run_config.strategies:
        if sc.param_grid:
            break
    else:
        click.echo("No param_grid found in config. Run with --grid only when param_grid is defined.")
        return

    dc = run_config.data[0]
    grid_results = grid_backtest(
        strategy_path=sc.strategy_path,
        config_path=sc.config_path,
        base_config=sc.config,
        param_grid=sc.param_grid,
        instrument_id=dc.instrument_id,
        bar_type=dc.bar_type or "",
        catalog_path=dc.catalog_path or "",
        start_time=dc.start_time or "",
        end_time=dc.end_time or "",
        starting_balances=run_config.venues[0].starting_balances if run_config.venues else ["100_000 USD"],
        fee_model=run_config.venues[0].fee_model if run_config.venues else None,
    )

    click.echo(f"\n========== Grid Backtest Results (top {top_n}) ==========")
    click.echo(f"Total combinations: {len(grid_results)}")
    click.echo("")
    for idx, r in enumerate(grid_results[:top_n], 1):
        click.echo(
            f"#{idx}  params={r.params}  PnL={r.total_pnl}  "
            f"Sharpe={r.sharpe_ratio}  DD={r.max_drawdown}  trades={r.total_trades}"
        )


@cli.command()
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False, help="Simulated trading: real data, SIM execution.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose output.")
def live(config: Path, dry_run: bool, verbose: bool) -> None:
    """Run live trading from a YAML configuration file.

    With --dry-run, data clients connect to real sources but orders go to a
    SIM venue instead of a real broker.
    """
    from trade_system_core.adapters import get_registry  # noqa: F401, PLC0415

    run_config = load_config(config)
    run_config = msgspec_replace(run_config, dry_run=dry_run)

    from trade_system_core.observability import init_observability  # noqa: PLC0415

    init_observability(run_config.observability)

    if verbose:
        click.echo(f"Loaded config: mode=live, trader_id={run_config.trader_id}")
        click.echo(f"  data_clients: {list(run_config.data_clients)}")
        click.echo(f"  exec_clients: {list(run_config.exec_clients)}")
        click.echo(f"  dry_run: {run_config.dry_run}")

    from trade_system_core.live import run_live  # noqa: PLC0415

    run_live(run_config)


@cli.command()
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.option("--tearsheet", is_flag=True, default=False, help="Generate tearsheet (backtest only).")
@click.option("--grid", is_flag=True, default=False, help="Enable matrix backtesting.")
@click.option("--dry-run", is_flag=True, default=False, help="Simulated trading (live only).")
@click.option("--top-n", default=10, show_default=True, help="Top N grid results.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose output.")
def run(config: Path, tearsheet: bool, grid: bool, dry_run: bool, top_n: int, verbose: bool) -> None:
    """Auto-detect mode from config and run.

    Reads the ``mode`` field from the YAML config and delegates to
    ``backtest`` or ``live`` accordingly.
    """
    run_config = load_config(config)
    mode = run_config.mode.lower()

    if mode == "backtest":
        ctx = click.get_current_context()
        ctx.invoke(backtest, config=config, tearsheet=tearsheet, grid=grid, top_n=top_n, verbose=verbose)
    elif mode == "live":
        ctx = click.get_current_context()
        ctx.invoke(live, config=config, dry_run=dry_run, verbose=verbose)
    else:
        raise click.UsageError(f"Unknown mode '{mode}' in config. Expected 'backtest' or 'live'.")


def msgspec_replace(obj, **kwargs):
    """Replace fields on a frozen msgspec struct (creates a new instance)."""
    import msgspec  # noqa: PLC0415

    data = msgspec.to_builtins(obj)
    data.update(kwargs)
    return msgspec.convert(data, type(obj))
