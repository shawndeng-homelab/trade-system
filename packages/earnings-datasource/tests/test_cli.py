"""Click-CLI tests for ``earnings-data``.

Uses Click's ``CliRunner`` to exercise the help text, argument
validation, and end-to-end flow with a mocked provider so no network
calls happen.
"""

from datetime import UTC
from datetime import date
from datetime import datetime
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from earnings_datasource import EarningsEvent
from earnings_datasource.cli import cli


def _ev(code: str = "AAPL.US", report: date | None = None) -> EarningsEvent:
    """Build a minimal valid EarningsEvent for CLI tests."""
    if report is None:
        report = date(2024, 2, 1)
    return EarningsEvent(
        code=code,
        symbol=code.split(".", 1)[0],
        report_date=datetime(report.year, report.month, report.day, tzinfo=UTC),
        fiscal_period_end=date(2023, 12, 31),
        session="amc",
        estimate_eps=2.11,
        actual_eps=2.18,
        eps_surprise=0.07,
        eps_surprise_pct=0.033175,
        currency="USD",
        source="eodhd",
    )


def test_help_top_level() -> None:
    """Top-level ``--help`` lists the subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "download" in result.output
    assert "cache" in result.output


def test_help_download() -> None:
    """``download --help`` documents every flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["download", "--help"])
    assert result.exit_code == 0
    for flag in (
        "--symbols",
        "--from",
        "--to",
        "--source",
        "--cache-dir",
        "--full",
        "--overlap-days",
        "--no-cache-window-days",
    ):
        assert flag in result.output


def test_help_cache() -> None:
    """``cache --help`` lists the size + clear subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "--help"])
    assert result.exit_code == 0
    assert "size" in result.output
    assert "clear" in result.output


def test_download_requires_symbols() -> None:
    """Omitting ``--symbols`` exits non-zero with a usage error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["download"])
    assert result.exit_code != 0
    assert "--symbols" in result.output


def test_download_rejects_unknown_source() -> None:
    """Unknown ``--source`` is rejected by Click's choice validator."""
    runner = CliRunner()
    result = runner.invoke(cli, ["download", "--symbols", "AAPL", "--source", "nope"])
    assert result.exit_code != 0
    assert "nope" in result.output


def test_download_full_flag_uses_fetch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--full`` dispatches to ``provider.fetch`` over the explicit date window."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))

    events = [_ev(report=date(2024, 2, 1)), _ev(code="MSFT.US", report=date(2024, 4, 25))]

    runner = CliRunner()
    with patch(
        "earnings_datasource.cli.EodhdEarningsProvider.fetch",
        return_value=events,
    ) as mock_fetch:
        result = runner.invoke(
            cli,
            [
                "download",
                "--symbols",
                "AAPL,MSFT",
                "--from",
                "2024-01-01",
                "--to",
                "2024-04-30",
                "--full",
                "--cache-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0, result.output
    mock_fetch.assert_called_once()
    assert "AAPL.US" in result.output
    assert "MSFT.US" in result.output
    assert (tmp_path / "cache" / "earnings" / "AAPL.US.parquet").exists()
    assert (tmp_path / "cache" / "earnings" / "MSFT.US.parquet").exists()


def test_default_uses_incremental_fetch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No flag (the default) dispatches to ``incremental_fetch``, not ``fetch``."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))

    runner = CliRunner()
    with (
        patch(
            "earnings_datasource.cli.EodhdEarningsProvider.incremental_fetch",
            return_value=[_ev()],
        ) as mock_inc,
        patch("earnings_datasource.cli.EodhdEarningsProvider.fetch") as mock_fetch,
    ):
        result = runner.invoke(
            cli,
            [
                "download",
                "--symbols",
                "AAPL",
                "--cache-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0, result.output
    mock_inc.assert_called_once()
    mock_fetch.assert_not_called()
    # The CLI defaults to a 2-year backfill for symbols with no cache.
    _, kwargs = mock_inc.call_args
    assert kwargs["no_cache_window_days"] == 730


def test_no_cache_window_days_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--no-cache-window-days`` overrides the 730-day default backfill."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))

    runner = CliRunner()
    with patch(
        "earnings_datasource.cli.EodhdEarningsProvider.incremental_fetch",
        return_value=[_ev()],
    ) as mock_inc:
        result = runner.invoke(
            cli,
            [
                "download",
                "--symbols",
                "AAPL",
                "--no-cache-window-days",
                "365",
                "--cache-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0, result.output
    _, kwargs = mock_inc.call_args
    assert kwargs["no_cache_window_days"] == 365


def test_full_flag_passes_no_cache_window_to_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--full`` uses ``--no-cache-window-days`` as the default start when --from is omitted."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))

    runner = CliRunner()
    with patch(
        "earnings_datasource.cli.EodhdEarningsProvider.fetch",
        return_value=[],
    ) as mock_fetch:
        result = runner.invoke(
            cli,
            [
                "download",
                "--full",
                "--symbols",
                "AAPL",
                "--no-cache-window-days",
                "90",
                "--cache-dir",
                str(tmp_path),
            ],
        )
    assert result.exit_code == 0, result.output
    args, _ = mock_fetch.call_args
    # args[1] is start_date, args[2] is end_date.
    start, end = args[1], args[2]
    assert (end - start).days == 90


def test_cache_size_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty cache prints the empty-cache sentinel."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "size"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower()


def test_cache_clear_requires_target(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``cache clear`` without a symbol and without ``--all`` is a usage error."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "clear"])
    assert result.exit_code != 0
    assert "SYMBOL" in result.output or "--all" in result.output


def test_cache_clear_rejects_symbol_and_all(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing both a SYMBOL and ``--all`` is a usage error."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "clear", "AAPL", "--all"])
    assert result.exit_code != 0


def test_cache_clear_all(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``cache clear --all -y`` removes every cached parquet file."""
    monkeypatch.setenv("OPTOPSY_DATA_DIR", str(tmp_path))

    cache_dir = tmp_path / "cache" / "earnings"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "AAPL.US.parquet").write_bytes(b"")
    (cache_dir / "MSFT.US.parquet").write_bytes(b"")

    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "clear", "--all", "-y"])
    assert result.exit_code == 0, result.output
    assert "Cleared 2" in result.output
    assert not list(cache_dir.glob("*.parquet"))
