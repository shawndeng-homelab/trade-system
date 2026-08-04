"""Tests for the parquet cache helper."""

from datetime import UTC
from datetime import datetime

import pandas as pd
import pytest
from earnings_datasource.providers.store import cache_path
from earnings_datasource.providers.store import merge_earnings
from earnings_datasource.providers.store import read_earnings
from earnings_datasource.providers.store import write_earnings


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_cache_path_under_opto_data_dir(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """``cache_path`` returns a path under ``<root>/cache/earnings/``."""
    p = cache_path("AAPL.US", root=tmp_optopsy_dir)
    assert p == tmp_optopsy_dir / "cache" / "earnings" / "AAPL.US.parquet"


def test_cache_path_uppercases_symbol(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """``cache_path`` uppercases the symbol so case variants collide on disk."""
    p = cache_path("aapl.us", root=tmp_optopsy_dir)
    assert p.name == "AAPL.US.parquet"


def test_read_missing_returns_none(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """Reading a symbol that was never written returns ``None``."""
    assert read_earnings("AAPL.US", root=tmp_optopsy_dir) is None


def test_write_then_read_roundtrip(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """A round-trip write/read preserves all rows and column values."""
    rows = [
        {
            "code": "AAPL.US",
            "symbol": "AAPL",
            "report_date": datetime(2024, 8, 1, tzinfo=UTC),
            "session": "amc",
            "actual_eps": 1.2,
        },
        {
            "code": "AAPL.US",
            "symbol": "AAPL",
            "report_date": datetime(2024, 11, 1, tzinfo=UTC),
            "session": "amc",
            "actual_eps": 1.5,
        },
    ]
    df = _df(rows)
    write_earnings("AAPL.US", df, root=tmp_optopsy_dir)
    out = read_earnings("AAPL.US", root=tmp_optopsy_dir)
    assert out is not None
    assert len(out) == 2
    assert list(out["code"]) == ["AAPL.US", "AAPL.US"]
    assert list(out["actual_eps"]) == [1.2, 1.5]


def test_merge_earnings_dedup(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """Merging with overlap drops duplicates on the natural key."""
    initial = _df(
        [
            {"code": "AAPL.US", "report_date": datetime(2024, 8, 1, tzinfo=UTC), "actual_eps": 1.0},
            {"code": "AAPL.US", "report_date": datetime(2024, 11, 1, tzinfo=UTC), "actual_eps": 1.5},
        ]
    )
    write_earnings("AAPL.US", initial, root=tmp_optopsy_dir)

    new = _df(
        [
            {"code": "AAPL.US", "report_date": datetime(2024, 8, 1, tzinfo=UTC), "actual_eps": 1.2},  # overlap
            {"code": "AAPL.US", "report_date": datetime(2025, 2, 1, tzinfo=UTC), "actual_eps": 1.7},
        ]
    )
    merged = merge_earnings("AAPL.US", new, dedup_cols=["code", "report_date"], root=tmp_optopsy_dir)
    # 3 unique rows: 2024-08 (newer value wins), 2024-11, 2025-02.
    assert len(merged) == 3
    # Compare via the date string to avoid pandas timestamp-equality quirks after parquet round-trip.
    merged = merged.assign(_d=merged["report_date"].astype(str).str[:10])
    aug = merged[merged["_d"] == "2024-08-01"]
    assert len(aug) == 1
    assert float(aug.iloc[0]["actual_eps"]) == 1.2  # last write wins


def test_merge_into_empty_cache(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """Merging into a missing cache creates the file with ``new_df``."""
    new = _df([{"code": "AAPL.US", "report_date": datetime(2024, 8, 1, tzinfo=UTC), "actual_eps": 1.2}])
    merged = merge_earnings("AAPL.US", new, dedup_cols=["code", "report_date"], root=tmp_optopsy_dir)
    assert len(merged) == 1
    out = read_earnings("AAPL.US", root=tmp_optopsy_dir)
    assert out is not None and len(out) == 1


def test_merge_empty_new_into_existing(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """An empty ``new_df`` leaves the existing cache untouched."""
    initial = _df([{"code": "AAPL.US", "report_date": datetime(2024, 8, 1, tzinfo=UTC), "actual_eps": 1.2}])
    write_earnings("AAPL.US", initial, root=tmp_optopsy_dir)
    empty = pd.DataFrame(columns=["code", "report_date", "actual_eps"])
    merged = merge_earnings("AAPL.US", empty, dedup_cols=["code", "report_date"], root=tmp_optopsy_dir)
    assert len(merged) == 1
    assert merged.iloc[0]["actual_eps"] == 1.2


def test_merge_aligns_columns(tmp_optopsy_dir: pytest.TempPathFactory) -> None:  # type: ignore[valid-type]
    """Old and new dataframes with different columns are aligned on concat."""
    initial = _df(
        [
            {
                "code": "AAPL.US",
                "report_date": datetime(2024, 8, 1, tzinfo=UTC),
                "actual_eps": 1.2,
            }
        ]
    )
    write_earnings("AAPL.US", initial, root=tmp_optopsy_dir)

    new = _df(
        [
            {
                "code": "AAPL.US",
                "report_date": datetime(2024, 11, 1, tzinfo=UTC),
                "estimate_eps": 1.4,  # new column
            }
        ]
    )
    merged = merge_earnings("AAPL.US", new, dedup_cols=["code", "report_date"], root=tmp_optopsy_dir)
    assert len(merged) == 2
    # The old row should have NaN in the new column.
    assert "estimate_eps" in merged.columns
    assert merged.iloc[0]["estimate_eps"] != merged.iloc[0]["estimate_eps"]  # NaN check
    assert merged.iloc[1]["estimate_eps"] == 1.4
