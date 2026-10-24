"""基于 Click 和 rich-click 的 simulate-market 命令行入口。"""

import json
from contextlib import contextmanager
from pathlib import Path

import rich_click as click

from options_strategies.simulation.config import SimulationConfig
from options_strategies.simulation.source import MonteCarloSource
from options_strategies.simulation.storage import SimulationDataset


CLI_HELP_CONFIG = click.RichHelpConfiguration(
    style_option="bold cyan",
    style_switch="bold cyan",
    style_command="bold cyan",
    style_options_panel_border="dim cyan",
    style_commands_panel_border="dim cyan",
    options_panel_title="选项",
    commands_panel_title="命令",
    errors_panel_title="错误",
)


@contextmanager
def command_errors():
    """将数据源错误交给 Click 展示并返回非零退出码。"""
    try:
        yield
    except (ValueError, OSError, KeyError, RuntimeError) as error:
        raise click.ClickException(str(error)) from error


def emit_json(value: dict) -> None:
    """保留可供脚本解析的 JSON 标准输出。"""
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.rich_config(help_config=CLI_HELP_CONFIG)
def main():
    """生成、验证和查看可复现的日频合成市场数据。"""


@main.command()
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="JSON 配置文件。",
)
@click.option(
    "--output",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="数据集输出目录。",
)
@click.option("--resume", is_flag=True, help="校验并跳过已完成路径，重建未完成路径。")
def generate(config_path: Path, output_dir: Path, resume: bool):
    """按配置分片生成股票、期权及结算数据。"""
    with command_errors():
        config = SimulationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        dataset = MonteCarloSource(config).generate_to(output_dir, resume=resume)
        emit_json(
            {
                "output": str(dataset.root),
                "paths": {key: value["status"] for key, value in dataset.manifest["paths"].items()},
            }
        )


@main.command()
@click.option(
    "--input",
    "input_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, readable=True, path_type=Path),
    help="需要完整校验的数据集目录。",
)
def validate(input_dir: Path):
    """检查文件摘要、数据边界及合约报价完整性。"""
    with command_errors():
        emit_json(SimulationDataset.open(input_dir).validate())


@main.command(name="inspect")
@click.option(
    "--input",
    "input_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, readable=True, path_type=Path),
    help="需要查看清单的数据集目录。",
)
def inspect_dataset(input_dir: Path):
    """查看配置、生成版本及各路径状态。"""
    with command_errors():
        emit_json(SimulationDataset.open(input_dir).manifest)


if __name__ == "__main__":
    main()
