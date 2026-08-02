"""Benchmark strategy -- rolling ATM call via optopsy."""

from options_strategies.benchmark.config import BenchmarkConfig
from options_strategies.benchmark.signals import benchmark_entry_dates
from options_strategies.benchmark.strategy import run_benchmark


__all__ = [
    "BenchmarkConfig",
    "benchmark_entry_dates",
    "run_benchmark",
]
