"""Tests for trade_system_core.cli — Click command parsing."""

from __future__ import annotations

from click.testing import CliRunner
from trade_system_core.cli import cli


class TestCliCommands:
    """Tests for CLI subcommand parsing and routing."""

    def test_cli_help(self):  # noqa: D102
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "backtest" in result.output
        assert "live" in result.output
        assert "run" in result.output

    def test_backtest_help(self):  # noqa: D102
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "--tearsheet" in result.output
        assert "--output-dir" in result.output

    def test_live_help(self):  # noqa: D102
        runner = CliRunner()
        result = runner.invoke(cli, ["live", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output

    def test_run_help(self):  # noqa: D102
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--tearsheet" in result.output
        assert "--dry-run" in result.output
