"""测量完整数据生成及校验的时间、内存和落盘大小。"""

import json
import platform
import resource
import time
from pathlib import Path

import rich_click as click
from options_strategies.simulation import MonteCarloSource
from options_strategies.simulation import SimulationConfig
from options_strategies.simulation.cli import CLI_HELP_CONFIG
from options_strategies.simulation.cli import command_errors


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.rich_config(help_config=CLI_HELP_CONFIG)
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
    help="保存数据及 benchmark.json 的新目录。",
)
@click.option("--paths", "n_paths", type=click.IntRange(min=1), default=1, show_default=True, help="生成路径数。")
def main(config_path: Path, output_dir: Path, n_paths: int):
    """测量完整数据生成及校验的时间、内存和落盘大小。"""
    with command_errors():
        run_benchmark(config_path, output_dir, n_paths)


def run_benchmark(config_path: Path, output_dir: Path, n_paths: int):
    """按路径串行采样性能，不累计持有历史期权报价。"""
    config = SimulationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    source = MonteCarloSource(config)
    checkpoints = []
    for path_id in range(n_paths):
        dataset = source.generate_to(output_dir, path_ids=[path_id], resume=path_id > 0)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        checkpoint = {
            "path_id": path_id,
            "elapsed_seconds": time.perf_counter() - started,
            "peak_rss_bytes": peak if platform.system() == "Darwin" else peak * 1024,
        }
        checkpoints.append(checkpoint)
        print(json.dumps({"checkpoint": checkpoint}), flush=True)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output = {
        "config": str(config_path),
        "config_sha256": config.fingerprint(),
        "paths": n_paths,
        "elapsed_seconds": time.perf_counter() - started,
        "pricing_cache_hits": sum(entry["pricing_cache_hits"] for entry in dataset.manifest["paths"].values()),
        "pricing_solver_calls": sum(entry["pricing_solver_calls"] for entry in dataset.manifest["paths"].values()),
        "peak_rss_bytes": peak if platform.system() == "Darwin" else peak * 1024,
        "dataset_bytes": sum(p.stat().st_size for p in dataset.root.rglob("*") if p.is_file()),
        "rows": {
            name: sum(entry["rows"][name] for entry in dataset.manifest["paths"].values())
            for name in ("stock", "options", "contracts", "settlements")
        },
        "platform": platform.platform(),
        "checkpoints": checkpoints,
        "provenance": dataset.manifest["provenance"],
    }
    (dataset.root / "benchmark.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
