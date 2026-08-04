"""Parquet cache helper for earnings calendar data.

The cache lives at ``$OPTOPSY_DATA_DIR/cache/earnings/{SYMBOL}.parquet``,
matching the layout optopsy uses for its own categories. We intentionally
do **not** route through optopsy's ``get_store()`` because:

1. ``PostgresStore`` is hard-coded to two table names
   (``options_data`` and ``stocks_data``); an ``"earnings"`` category
   would ``KeyError`` on insert.
2. Keeping our own helper keeps optopsy a weak (plugin-entry-point)
   dependency rather than a strong runtime one.
3. Reduces AGPL surface area: the new package only imports optopsy in
   ``entry_point.py``.
"""

import os
from pathlib import Path

import pandas as pd


CACHE_CATEGORY = "earnings"
_DEFAULT_DATA_DIR = Path("~/.optopsy").expanduser()


def _data_dir() -> Path:
    """Resolve the optopsy data root, honoring ``OPTOPSY_DATA_DIR``."""
    env = os.environ.get("OPTOPSY_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return _DEFAULT_DATA_DIR


def cache_path(symbol: str, *, root: Path | None = None) -> Path:
    """Return the parquet path for *symbol* under the given (or default) root.

    The symbol is uppercased so case-variants collapse to the same file.
    """
    base = root or _data_dir()
    return base / "cache" / CACHE_CATEGORY / f"{symbol.upper()}.parquet"


def read_earnings(symbol: str, *, root: Path | None = None) -> pd.DataFrame | None:
    """Read the cached earnings DataFrame for *symbol*, or ``None`` if absent."""
    path = cache_path(symbol, root=root)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_earnings(
    symbol: str,
    df: pd.DataFrame,
    *,
    root: Path | None = None,
) -> None:
    """Write *df* to the cache, overwriting any existing file for *symbol*."""
    path = cache_path(symbol, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")


def merge_earnings(
    symbol: str,
    new_df: pd.DataFrame,
    *,
    dedup_cols: list[str] | None = None,
    root: Path | None = None,
) -> pd.DataFrame:
    """Merge *new_df* into the cached file for *symbol*, deduplicating.

    Args:
        symbol: Vendor-native ticker (e.g. ``AAPL.US``).
        new_df: New rows to merge in.
        dedup_cols: Columns that uniquely identify a row (defaults to all).
        root: Override the data root (for tests).

    Returns:
        The merged DataFrame that was written to disk.
    """
    if new_df.empty:
        existing = read_earnings(symbol, root=root)
        if existing is None:
            empty = new_df.copy()
            write_earnings(symbol, empty, root=root)
            return empty
        return existing

    existing = read_earnings(symbol, root=root)
    if existing is None or existing.empty:
        merged = new_df.copy()
    else:
        # Align columns so concat doesn't introduce NaN-only columns.
        all_cols = list(dict.fromkeys([*existing.columns, *new_df.columns]))
        merged = pd.concat(
            [existing.reindex(columns=all_cols), new_df.reindex(columns=all_cols)],
            ignore_index=True,
        )

    merged = merged.drop_duplicates(subset=dedup_cols, keep="last") if dedup_cols else merged.drop_duplicates()
    merged = merged.reset_index(drop=True)
    write_earnings(symbol, merged, root=root)
    return merged
