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
from earnings_datasource.providers.store import merge_earnings
from rich.console import Console
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
        default=(date.today() - timedelta(days=365)).isoformat(),
        help="Inclusive start date (YYYY-MM-DD). Default: 1 year ago.",
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
    args = parser.parse_args()

    if args.cache_dir:
        # Set before any cache helper runs so the override takes effect.
        os.environ["OPTOPSY_DATA_DIR"] = args.cache_dir

    provider = _PROVIDERS[args.source]()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    events = provider.fetch(symbols, start, end)

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
    table.add_column("Report (UTC)", style="magenta")
    table.add_column("Session", style="green")
    table.add_column("EPS surprise", justify="right")
    table.add_column("Rev surprise", justify="right")
    for ev in sorted(events, key=lambda e: e.report_date):
        eps = f"{ev.eps_surprise:+.2f}" if ev.eps_surprise is not None else "—"
        rev = f"{ev.revenue_surprise:+,.0f}" if ev.revenue_surprise is not None else "—"
        table.add_row(
            ev.code,
            ev.symbol,
            ev.report_date.strftime("%Y-%m-%d %H:%M"),
            ev.session,
            eps,
            rev,
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
