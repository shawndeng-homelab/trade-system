"""Test fixtures: redirect optopsy cache to a tmp dir and clean per test.

The session-scoped ``tmp_optopsy_dir`` fixture sets ``OPTOPSY_DATA_DIR``
to a temporary directory so tests never touch the user's real
``~/.optopsy/cache/earnings/`` data.

The autouse ``_clean_cache`` fixture wipes any parquet files created in
the previous test so each test starts with a clean slate.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tmp_optopsy_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Point ``OPTOPSY_DATA_DIR`` at a tmp dir for the whole test session."""
    d = tmp_path_factory.mktemp("optopsy_data")
    os.environ["OPTOPSY_DATA_DIR"] = str(d)
    return d


@pytest.fixture(autouse=True)
def _clean_cache(tmp_optopsy_dir: Path) -> None:
    """Wipe the earnings category between tests so each test starts clean."""
    earnings = tmp_optopsy_dir / "cache" / "earnings"
    if earnings.exists():
        for f in earnings.glob("*.parquet"):
            f.unlink()
    yield
    if earnings.exists():
        for f in earnings.glob("*.parquet"):
            f.unlink()
