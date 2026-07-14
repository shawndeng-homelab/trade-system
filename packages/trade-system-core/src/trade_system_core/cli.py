"""Click CLI entry point for trade-system.

Commands:

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
    """Trade system CLI — unified entry point for backtest and live trading."""


@cli.command()
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.option("--tearsheet", is_flag=True, default=False, help="Generate an interactive HTML tearsheet.")
@click.option("--output-dir", default=None, help="Directory for HTML reports. Defaults to .tmp")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose output.")
def backtest(config: Path, tearsheet: bool, output_dir: str | None, verbose: bool) -> None:
    """Run a backtest from a YAML configuration file."""
    from trade_system_core.adapters import get_registry  # noqa: F401, PLC0415

    run_config = load_config(config)

    from trade_system_core.observability import init_observability  # noqa: PLC0415

    init_observability(run_config.observability)

    if verbose:
        click.echo(f"Loaded config: mode={run_config.mode}, trader_id={run_config.trader_id}")
        click.echo(f"  venues: {[v.name for v in run_config.venues]}")
        click.echo(f"  strategies: {[s.strategy_path for s in run_config.strategies]}")

    from trade_system_core.backtest import run_backtest  # noqa: PLC0415

    results = run_backtest(run_config, tearsheet=tearsheet, output_dir=output_dir)

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
        out = output_dir or ".tmp"
        click.echo(f"\nTearsheet(s) written to: {out}/tearsheet_*.html")


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
@click.option("--output-dir", default=None, help="Directory for HTML reports. Defaults to .tmp")
@click.option("--dry-run", is_flag=True, default=False, help="Simulated trading (live only).")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Verbose output.")
def run(
    config: Path,
    tearsheet: bool,
    output_dir: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Auto-detect mode from config and run.

    Reads the ``mode`` field from the YAML config and delegates to
    ``backtest`` or ``live`` accordingly.
    """
    run_config = load_config(config)
    mode = run_config.mode.lower()

    if mode == "backtest":
        ctx = click.get_current_context()
        ctx.invoke(
            backtest,
            config=config,
            tearsheet=tearsheet,
            output_dir=output_dir,
            verbose=verbose,
        )
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
