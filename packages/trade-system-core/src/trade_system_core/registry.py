"""Adapter registry for data clients, execution clients, and fee models.

Adapters register themselves at import time; the runner looks them up by name
when building a :class:`~nautilus_trader.backtest.node.BacktestNode` or
:class:`~nautilus_trader.live.node.TradingNode`.

"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from nautilus_trader.backtest.models import FeeModel
    from nautilus_trader.live.factories import LiveDataClientFactory
    from nautilus_trader.live.factories import LiveExecClientFactory


class AdapterRegistry:
    """Global registry mapping adapter names to their factory classes.

    Each adapter (Massive, IBKR, Binance, …) calls the ``register_*`` methods
    at import time so that YAML configs can reference adapters by name.

    """

    def __init__(self) -> None:  # noqa: D107
        self._data_client_factories: dict[str, type[LiveDataClientFactory]] = {}
        self._exec_client_factories: dict[str, type[LiveExecClientFactory]] = {}
        self._fee_models: dict[str, type[FeeModel]] = {}

    # ── Data client factories ──────────────────────────────────────────

    def register_data_client(self, name: str, factory: type[LiveDataClientFactory]) -> None:
        """Register a live data client factory under *name*."""
        name = name.upper()
        if name in self._data_client_factories:
            msg = f"Data client factory '{name}' already registered"
            raise ValueError(msg)
        self._data_client_factories[name] = factory

    def get_data_client_factory(self, name: str) -> type[LiveDataClientFactory]:
        """Return the data client factory registered under *name*."""
        name = name.upper()
        if name not in self._data_client_factories:
            available = ", ".join(sorted(self._data_client_factories)) or "(none)"
            msg = f"Data client factory '{name}' not found. Available: {available}"
            raise KeyError(msg)
        return self._data_client_factories[name]

    def list_data_client_names(self) -> list[str]:
        """Return sorted names of all registered data client factories."""
        return sorted(self._data_client_factories)

    # ── Exec client factories ──────────────────────────────────────────

    def register_exec_client(self, name: str, factory: type[LiveExecClientFactory]) -> None:
        """Register a live execution client factory under *name*."""
        name = name.upper()
        if name in self._exec_client_factories:
            msg = f"Exec client factory '{name}' already registered"
            raise ValueError(msg)
        self._exec_client_factories[name] = factory

    def get_exec_client_factory(self, name: str) -> type[LiveExecClientFactory]:
        """Return the exec client factory registered under *name*."""
        name = name.upper()
        if name not in self._exec_client_factories:
            available = ", ".join(sorted(self._exec_client_factories)) or "(none)"
            msg = f"Exec client factory '{name}' not found. Available: {available}"
            raise KeyError(msg)
        return self._exec_client_factories[name]

    def list_exec_client_names(self) -> list[str]:
        """Return sorted names of all registered exec client factories."""
        return sorted(self._exec_client_factories)

    # ── Fee models ─────────────────────────────────────────────────────

    def register_fee_model(self, name: str, model: type[FeeModel]) -> None:
        """Register a fee model class under *name*."""
        if name in self._fee_models:
            msg = f"Fee model '{name}' already registered"
            raise ValueError(msg)
        self._fee_models[name] = model

    def get_fee_model(self, name: str) -> type[FeeModel]:
        """Return the fee model class registered under *name*."""
        if name not in self._fee_models:
            available = ", ".join(sorted(self._fee_models)) or "(none)"
            msg = f"Fee model '{name}' not found. Available: {available}"
            raise KeyError(msg)
        return self._fee_models[name]

    def list_fee_model_names(self) -> list[str]:
        """Return sorted names of all registered fee models."""
        return sorted(self._fee_models)


# ── Module-level singleton ─────────────────────────────────────────────

_registry = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    """Return the global :class:`AdapterRegistry` singleton."""
    return _registry
