"""Click-based CLI for the earnings-datasource package.

Mirrors the structure of ``optopsy-data``: a top-level group with
``download`` and ``cache`` subcommands. Install the package and run
``earnings-data --help`` to see the full surface.

Examples::

    earnings-data download --symbols AAPL,MSFT      # default: incremental
    earnings-data download --full --symbols AAPL    # full re-fetch
    earnings-data cache size
    earnings-data cache clear AAPL
"""

import os
import sys
from collections.abc import Callable
from datetime import date as date_cls
from datetime import datetime
from datetime import timedelta
from typing import Any

import click
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn
from rich.table import Table

from earnings_datasource import EarningsCalendar
from earnings_datasource import EodhdEarningsProvider
from earnings_datasource.providers.eodhd import _month_windows
from earnings_datasource.providers.store import CACHE_CATEGORY
from earnings_datasource.providers.store import _data_dir
from earnings_datasource.providers.store import merge_earnings


# Registry of vendor providers; ``--source`` selects one. New vendors slot
# in here without changing the CLI surface.
_PROVIDERS: dict[str, type] = {
    "eodhd": EodhdEarningsProvider,
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _resolve_provider(name: str) -> Any:
    """Instantiate a provider by name, mapping init errors to a clean usage error."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        msg = f"Unknown source {name!r}. Choices: {sorted(_PROVIDERS)}"
        raise click.UsageError(msg)
    try:
        return cls()
    except Exception as exc:
        raise click.UsageError(str(exc)) from exc


def _print_summary(events: list, console: Console) -> None:
    """Render a Rich table summarising the events just fetched."""
    if not events:
        console.print("[yellow]No earnings events fetched.[/yellow]")
        return

    table = Table(title="Earnings calendar", show_header=True, header_style="bold")
    table.add_column("Code", style="cyan")
    table.add_column("Symbol", style="cyan")
    table.add_column("Report", style="magenta")
    table.add_column("Session", style="green")
    table.add_column("EPS surprise", justify="right")
    table.add_column("Surprise %", justify="right")
    for ev in sorted(events, key=lambda e: e.report_date):
        eps = f"{ev.eps_surprise:+.2f}" if ev.eps_surprise is not None else "—"
        pct = f"{ev.eps_surprise_pct:+.2%}" if ev.eps_surprise_pct is not None else "—"
        table.add_row(
            ev.code,
            ev.symbol,
            ev.report_date.strftime("%Y-%m-%d"),
            ev.session,
            eps,
            pct,
        )
    console.print(table)


def _persist(events: list, console: Console) -> None:
    """Group events by vendor code and merge into the local parquet cache."""
    if not events:
        return
    by_code: dict[str, list] = {}
    for ev in events:
        by_code.setdefault(ev.code, []).append(ev)
    for code, ev_list in by_code.items():
        df = EarningsCalendar(events=ev_list, source="eodhd").to_dataframe()
        merged = merge_earnings(code, df, dedup_cols=["code", "report_date_utc"])
        console.print(f"  [green]cached[/green] {code} [dim]→[/dim] {len(merged)} rows")


def _format_bytes(n: float) -> str:
    """Format a byte count as a human-readable string (e.g. ``"1.2 MB"``)."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── CLI group ─────────────────────────────────────────────────────────────


@click.group(
    name="earnings-data",
    help="Download and manage the EODHD earnings calendar cache.",
)
@click.version_option(package_name="earnings-datasource")
def cli() -> None:
    """Top-level entry point for the earnings-data console script."""


# ── download subcommand ───────────────────────────────────────────────────


@cli.command()
@click.option(
    "--symbols",
    required=True,
    help="Comma-separated tickers (e.g. AAPL,MSFT). Bare tickers default to .US.",
)
@click.option(
    "--from",
    "from_date",
    default=None,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help=(
        "Inclusive start date (YYYY-MM-DD). Only used with --full; the "
        "default incremental mode infers the start from each symbol's "
        "local cache. Default: --no-cache-window-days back from --to."
    ),
)
@click.option(
    "--to",
    "to_date",
    default=None,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive end date (YYYY-MM-DD). Default: today.",
)
@click.option(
    "--source",
    default="eodhd",
    type=click.Choice(sorted(_PROVIDERS), case_sensitive=False),
    help="Data source (default: eodhd).",
)
@click.option(
    "--cache-dir",
    default=None,
    type=click.Path(file_okay=False, dir_okay=True, writable=True),
    help="Override OPTOPSY_DATA_DIR for this run (default: env var or ~/.optopsy).",
)
@click.option(
    "--full",
    "force_full",
    is_flag=True,
    help=(
        "Force a full re-fetch of the requested date window instead of the "
        "default incremental behaviour. The default inspects each symbol's "
        "local cache and only queries the API for rows newer than "
        "(max cached report_date - overlap-days); symbols with no cache "
        "fall back to a 2-year backfill (override with --no-cache-window-days). "
        "The --from flag is ignored in incremental mode."
    ),
)
@click.option(
    "--overlap-days",
    default=7,
    type=click.IntRange(min=0),
    show_default=True,
    help=(
        "Days of overlap with the existing cache (used by the default incremental mode to catch late vendor updates)."
    ),
)
@click.option(
    "--no-cache-window-days",
    default=730,
    type=click.IntRange(min=1),
    show_default=True,
    help=(
        "For symbols with no local cache, how many days back to backfill "
        "in the default incremental mode (default: 730 = 2 years). Also "
        "used as the --full default window when --from is omitted."
    ),
)
def download(
    symbols: str,
    from_date: datetime | None,
    to_date: datetime | None,
    source: str,
    cache_dir: str | None,
    force_full: bool,
    overlap_days: int,
    no_cache_window_days: int,
) -> None:
    """Download earnings events for SYMBOLS to the local cache (incremental by default)."""
    # Apply overrides *before* any provider/store call so they take effect.
    if cache_dir:
        os.environ["OPTOPSY_DATA_DIR"] = cache_dir

    end = to_date.date() if to_date is not None else date_cls.today()
    start = from_date.date() if from_date is not None else end - timedelta(days=no_cache_window_days)

    provider = _resolve_provider(source)
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    console = Console()
    use_progress = console.is_terminal

    if not force_full:
        incremental_fetch: Callable | None = getattr(provider, "incremental_fetch", None)
        if incremental_fetch is None:
            console.print(f"[red]Provider {source!r} does not support incremental fetch[/red]")
            sys.exit(1)

        def _line(idx: int, total: int, w_from: date_cls, w_to: date_cls) -> None:
            console.print(f"  [dim]window {idx}/{total}[/dim] [cyan]{w_from}[/cyan] → [cyan]{w_to}[/cyan]")

        events = incremental_fetch(
            symbol_list,
            end_date=end,
            overlap_days=overlap_days,
            no_cache_window_days=no_cache_window_days,
            on_window=_line,
        )
    else:
        windows = _month_windows(start, end)
        total = len(windows)

        def _line(idx: int, total_w: int, w_from: date_cls, w_to: date_cls) -> None:
            console.print(f"  [dim]window {idx}/{total_w}[/dim]  [cyan]{w_from}[/cyan] → [cyan]{w_to}[/cyan]")

        if use_progress and total > 0:
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:
                task_id = progress.add_task(f"Fetching {total} windows", total=total)

                def _bar(idx: int, total_w: int, w_from: date_cls, w_to: date_cls) -> None:
                    progress.update(
                        task_id,
                        completed=idx,
                        total=total_w,
                        description=f"window {idx}/{total_w}  {w_from} → {w_to}",
                    )

                events = provider.fetch(symbol_list, start, end, on_window=_bar)
                progress.update(task_id, completed=total, total=total)
        else:
            events = provider.fetch(symbol_list, start, end, on_window=_line)

    _print_summary(events, console)
    _persist(events, console)


# ── cache subcommand ──────────────────────────────────────────────────────


@cli.group(help="Inspect and manage the on-disk earnings cache.")
def cache() -> None:
    """Cache management subcommands."""


@cache.command("size")
def cache_size() -> None:
    """Print per-symbol cache sizes and a total."""
    root = _data_dir() / "cache" / CACHE_CATEGORY
    if not root.exists() or not any(root.glob("*.parquet")):
        click.echo("Cache is empty.")
        return
    total = 0
    for path in sorted(root.glob("*.parquet")):
        size = path.stat().st_size
        total += size
        click.echo(f"  {path.stem:<20s} {_format_bytes(size):>10s}")
    click.echo(f"  {'Total':<20s} {_format_bytes(total):>10s}")


@cache.command("clear")
@click.argument("symbol", required=False, default=None)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.option(
    "--all",
    "clear_all",
    is_flag=True,
    help="Clear every cached earnings file (equivalent to omitting SYMBOL).",
)
def cache_clear(symbol: str | None, yes: bool, clear_all: bool) -> None:
    """Delete cached parquet files for SYMBOL (or all of them with --all)."""
    # Validate arguments *before* inspecting the cache so empty caches
    # still report usage errors.
    if symbol and clear_all:
        msg = "Pass either SYMBOL or --all, not both."
        raise click.UsageError(msg)
    if not symbol and not clear_all:
        msg = "Provide a SYMBOL or pass --all."
        raise click.UsageError(msg)

    root = _data_dir() / "cache" / CACHE_CATEGORY
    targets = [root / f"{symbol.upper()}.parquet"] if symbol else sorted(root.glob("*.parquet"))

    if not yes and not click.confirm(f"Delete {len(targets)} file(s)?"):
        click.echo("Aborted.")
        return

    count = 0
    for p in targets:
        if p.exists():
            p.unlink()
            count += 1
    click.echo(f"Cleared {count} cached file(s).")


if __name__ == "__main__":
    cli()
