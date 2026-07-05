"""trade-system-core: unified runner for backtest, live trading, and parameter optimisation."""

from trade_system_core.backtest import grid_backtest
from trade_system_core.backtest import quick_backtest
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
    "grid_backtest",
    "load_config",
    "quick_backtest",
    "run_backtest",
    "run_live",
]
