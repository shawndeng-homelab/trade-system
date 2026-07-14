"""trade-system-core: unified runner for backtest, live trading, and parameter optimisation."""

from trade_system_core.backtest import run_backtest
from trade_system_core.config import load_config
from trade_system_core.live import run_live
from trade_system_core.registry import AdapterRegistry
from trade_system_core.registry import get_registry
from trade_system_core.telemetry import InstrumentedStrategy


__all__ = [
    "AdapterRegistry",
    "InstrumentedStrategy",
    "get_registry",
    "load_config",
    "run_backtest",
    "run_live",
]
