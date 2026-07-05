"""Built-in adapter auto-registration.

Importing this module triggers registration of all available adapters into
the global :class:`~trade_system_core.registry.AdapterRegistry`.  Adapters
whose dependencies are not installed are silently skipped.

"""

from __future__ import annotations

from trade_system_core.registry import get_registry


def _register_all() -> None:
    """Attempt to register every built-in adapter; skip on import failure."""
    registry = get_registry()

    # ── Fee models from trade-system-venues ────────────────────────────
    try:
        from trade_system_venues.ibkr.fee import IBKRFeeModel  # noqa: PLC0415

        registry.register_fee_model("ibkr_tiered", IBKRFeeModel)
    except (ImportError, AttributeError):
        pass

    try:
        from trade_system_venues.binance.fee import BinanceFeeModel  # noqa: PLC0415

        registry.register_fee_model("binance_spot", BinanceFeeModel)
    except (ImportError, AttributeError):
        pass

    # ── Live data client: Massive ──────────────────────────────────────
    try:
        from trade_system_massive.factories import MassiveLiveDataClientFactory  # noqa: PLC0415

        registry.register_data_client("MASSIVE", MassiveLiveDataClientFactory)
    except (ImportError, AttributeError):
        pass

    # ── Live data + exec client: Binance ───────────────────────────────
    try:
        from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory  # noqa: PLC0415

        registry.register_data_client("BINANCE", BinanceLiveDataClientFactory)
    except (ImportError, AttributeError):
        pass

    try:
        from nautilus_trader.adapters.binance.factories import BinanceLiveExecClientFactory  # noqa: PLC0415

        registry.register_exec_client("BINANCE", BinanceLiveExecClientFactory)
    except (ImportError, AttributeError):
        pass

    # ── Live data + exec client: IBKR ──────────────────────────────────
    try:
        from nautilus_trader.adapters.interactive_brokers.factories import (  # noqa: PLC0415
            InteractiveBrokersLiveDataClientFactory,
        )

        registry.register_data_client("IBKR", InteractiveBrokersLiveDataClientFactory)
    except (ImportError, AttributeError):
        pass

    try:
        from nautilus_trader.adapters.interactive_brokers.factories import (  # noqa: PLC0415
            InteractiveBrokersLiveExecClientFactory,
        )

        registry.register_exec_client("IBKR", InteractiveBrokersLiveExecClientFactory)
    except (ImportError, AttributeError):
        pass


_register_all()
