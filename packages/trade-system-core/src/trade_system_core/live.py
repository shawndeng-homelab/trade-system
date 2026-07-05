"""Live trading runner wrapping :class:`~nautilus_trader.live.node.TradingNode`.

Builds a :class:`~nautilus_trader.live.node.TradingNode` from a
:class:`~trade_system_core.config.RunConfig`, wires up data and execution
client factories from the :class:`~trade_system_core.registry.AdapterRegistry`,
and runs the node.

"""

from __future__ import annotations

import signal

from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from trade_system_core.config import RunConfig
from trade_system_core.registry import get_registry


def run_live(config: RunConfig) -> None:
    """Build and run a live :class:`TradingNode` from *config*.

    The node is built with data and execution client factories looked up from
    the global :class:`~trade_system_core.registry.AdapterRegistry`.  When
    ``config.dry_run`` is ``True``, no real execution clients are registered;
    the node still connects to data sources for live market data but routes
    orders to a SIM venue instead.

    Parameters
    ----------
    config : RunConfig
        The loaded YAML configuration with ``mode="live"``.

    """
    registry = get_registry()

    # Build TradingNodeConfig from the YAML config
    node_config = TradingNodeConfig(
        trader_id=config.trader_id,
        data_clients=config.data_clients,
        exec_clients=config.exec_clients if not config.dry_run else {},
    )

    node = TradingNode(config=node_config)

    # ── Register data client factories ──────────────────────────────────
    for adapter_name in config.data_clients:
        try:
            factory = registry.get_data_client_factory(adapter_name)
            node.add_data_client_factory(adapter_name, factory)
        except KeyError:
            msg = f"Warning: data client adapter '{adapter_name}' not found in registry, skipping"
            print(msg)

    # ── Register exec client factories (skip in dry_run) ────────────────
    if not config.dry_run:
        for adapter_name in config.exec_clients:
            try:
                factory = registry.get_exec_client_factory(adapter_name)
                node.add_exec_client_factory(adapter_name, factory)
            except KeyError:
                msg = f"Warning: exec client adapter '{adapter_name}' not found in registry, skipping"
                print(msg)

    # ── Build and run ───────────────────────────────────────────────────
    node.build()

    # Install signal handlers for graceful shutdown

    loop = node.get_event_loop()

    def _shutdown_handler(sig: signal.Signals) -> None:  # type: ignore[type-arg]
        node.get_logger().warning(f"Received {sig.name}, shutting down")
        node.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:  # noqa: SIM105
            loop.add_signal_handler(sig, _shutdown_handler, sig)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler on ProactorEventLoop
            pass

    if config.dry_run:
        print("⚠️  DRY RUN MODE — no real orders will be submitted")

    node.run()
