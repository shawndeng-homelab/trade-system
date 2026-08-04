r"""Download the EODHD earnings calendar for one or more symbols.

Caches results to ``$OPTOPSY_DATA_DIR/cache/earnings/{SYMBOL}.parquet`` so
they can be loaded by ``earnings_datasource.providers.store.read_earnings``.

Usage::

    EODHD_API_KEY=... python scripts/download_earnings_calendar.py \\
        --symbols AAPL,MSFT --from 2024-01-01 --to 2024-03-31

    EODHD_API_KEY=... python scripts/download_earnings_calendar.py \\
        --symbols AAPL --from 2024-01-01 --to 2024-03-31 --cache-dir ./tmp/cache
"""

import argparse
import os
import sys
from datetime import date
from datetime import timedelta

from earnings_datasource import EarningsCalendar
from earnings_datasource import EodhdEarningsProvider
from earnings_datasource.providers.eodhd import _month_windows
from earnings_datasource.providers.store import merge_earnings
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn
from rich.table import Table


_PROVIDERS = {"eodhd": EodhdEarningsProvider}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download the EODHD earnings calendar to the optopsy cache.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated tickers (e.g. AAPL,MSFT). Bare tickers default to .US.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help=(
            "Inclusive start date (YYYY-MM-DD). Ignored when --incremental is set "
            "(start is inferred from the local cache)."
        ),
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=date.today().isoformat(),
        help="Inclusive end date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--source",
        default="eodhd",
        choices=sorted(_PROVIDERS),
        help="Data source (default: eodhd).",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override OPTOPSY_DATA_DIR for this run (default: env var or ~/.optopsy).",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Only fetch rows the local cache is missing. The query window starts at "
            "(max cached report_date - 7 days) per symbol, or 1 year back for symbols "
            "with no cache. The --from flag is ignored when this is set."
        ),
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=7,
        help="Days of overlap with the existing cache (only used with --incremental).",
    )
    args = parser.parse_args()

    if args.cache_dir:
        # Set before any cache helper runs so the override takes effect.
        os.environ["OPTOPSY_DATA_DIR"] = args.cache_dir

    provider = _PROVIDERS[args.source]()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    end = date.fromisoformat(args.to_date)
    # When stdout is a TTY, render an in-place Rich progress bar; in piped
    # or non-interactive contexts (e.g. ``just`` invokes), Rich cannot
    # redraw in place, so we print per-window lines as a fallback.
    use_progress = Console().is_terminal
    console = Console(force_terminal=use_progress)

    # Set up a Rich progress bar that the provider's ``on_window`` callback
    # will advance. We do a dry-run window count first so the bar has the
    # correct total; that requires knowing the start date.
    if args.incremental:
        if args.from_date is None:
            args.from_date = (date.today() - timedelta(days=365)).isoformat()
        start = date.fromisoformat(args.from_date)

        # For incremental mode we don't know the exact window count up
        # front (per-symbol start dates depend on the cache). Pass a
        # callback that prints per-window progress without a determinate
        # bar — the outer per-symbol progress is good enough.
        def _incremental_callback(idx: int, total: int, w_from: date, w_to: date) -> None:
            console.print(f"  [dim]window {idx}/{total}[/dim] [cyan]{w_from}[/cyan] → [cyan]{w_to}[/cyan]")

        if args.incremental:
            incremental_fetch = getattr(provider, "incremental_fetch", None)
            if incremental_fetch is None:
                msg = f"Provider {args.source!r} does not support --incremental"
                console.print(f"[red]{msg}[/red]")
                return 1
            events = incremental_fetch(
                symbols,
                end_date=end,
                overlap_days=args.overlap_days,
                on_window=_incremental_callback,
            )
    else:
        if args.from_date is None:
            args.from_date = (date.today() - timedelta(days=365)).isoformat()
        start = date.fromisoformat(args.from_date)
        windows = _month_windows(start, end)
        total = len(windows)

        def _line_callback(idx: int, total_w: int, w_from: date, w_to: date) -> None:
            console.print(f"  [dim]window {idx}/{total_w}[/dim]  [cyan]{w_from}[/cyan] → [cyan]{w_to}[/cyan]")

        if use_progress:
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:
                task_id = progress.add_task(f"Fetching {total} windows", total=total)

                def _on_window(idx: int, total_w: int, w_from: date, w_to: date) -> None:
                    progress.update(
                        task_id,
                        completed=idx,
                        total=total_w,
                        description=f"window {idx}/{total_w}  {w_from} → {w_to}",
                    )

                events = provider.fetch(symbols, start, end, on_window=_on_window)
                progress.update(task_id, completed=total, total=total)
        else:
            events = provider.fetch(symbols, start, end, on_window=_line_callback)

    console = Console()
    if not events:
        console.print(f"[yellow]No earnings events found for {symbols} in {start}..{end}.[/yellow]")
        return 0

    # Group by vendor-native code and persist.
    by_code: dict[str, list] = {}
    for ev in events:
        by_code.setdefault(ev.code, []).append(ev)

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

    for code, ev_list in by_code.items():
        df = EarningsCalendar(events=ev_list, source="eodhd").to_dataframe()
        merged = merge_earnings(code, df, dedup_cols=["code", "report_date_utc"])
        console.print(
            f"  [green]cached[/green] {code} [dim]→[/dim] {len(merged)} rows in {code.split('.', 1)[-1]} exchange cache"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
