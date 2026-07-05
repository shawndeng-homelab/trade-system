"""Tests for trade_system_core.observability — OTel initialization idempotency."""

from __future__ import annotations

from trade_system_core.config import ObservabilityConfig
from trade_system_core.observability import init_observability
from trade_system_core.observability import shutdown_observability


class TestObservabilityInit:
    """Tests for OTel initialization."""

    def test_init_when_disabled(self):  # noqa: D102
        config = ObservabilityConfig(enabled=False)
        # Should be a no-op
        init_observability(config)
        # No exception means success

    def test_init_idempotent(self):
        """Calling init_observability twice should not error."""
        from trade_system_core import observability  # noqa: PLC0415

        # Reset the module flag
        observability._initialized = False

        config = ObservabilityConfig(enabled=False)
        init_observability(config)
        init_observability(config)
        # No double-initialization error

    def test_shutdown_no_error(self):
        """Shutdown should not raise even if nothing was initialized."""
        from trade_system_core import observability  # noqa: PLC0415

        observability._initialized = False
        shutdown_observability()
