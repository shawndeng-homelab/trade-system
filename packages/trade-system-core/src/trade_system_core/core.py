"""trade-system-core: unified runner for backtest, live trading, and parameter optimisation.

This package provides:

- :func:`~trade_system_core.backtest.run_backtest` — full-config backtest runner
- :func:`~trade_system_core.live.run_live` — live trading node runner
- :func:`~trade_system_core.config.load_config` — YAML configuration loader
- :class:`~trade_system_core.registry.AdapterRegistry` — pluggable adapter registration
- :class:`~trade_system_core.telemetry.InstrumentedStrategy` — OTel-instrumented strategy mixin

"""
