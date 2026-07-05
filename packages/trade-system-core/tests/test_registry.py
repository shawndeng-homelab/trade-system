"""Tests for trade_system_core.registry."""

from __future__ import annotations

import pytest
from trade_system_core.registry import AdapterRegistry


class TestAdapterRegistry:
    """Tests for the adapter registration and lookup."""

    def test_register_and_get_fee_model(self):  # noqa: D102
        registry = AdapterRegistry()

        class FakeFeeModel:
            pass

        registry.register_fee_model("test_model", FakeFeeModel)
        assert registry.get_fee_model("test_model") is FakeFeeModel

    def test_register_and_get_data_client(self):  # noqa: D102
        registry = AdapterRegistry()

        class FakeDataClientFactory:
            pass

        registry.register_data_client("TEST", FakeDataClientFactory)
        assert registry.get_data_client_factory("TEST") is FakeDataClientFactory

    def test_register_and_get_exec_client(self):  # noqa: D102
        registry = AdapterRegistry()

        class FakeExecClientFactory:
            pass

        registry.register_exec_client("TEST", FakeExecClientFactory)
        assert registry.get_exec_client_factory("TEST") is FakeExecClientFactory

    def test_duplicate_registration_raises(self):  # noqa: D102
        registry = AdapterRegistry()

        class FakeModel:
            pass

        registry.register_fee_model("dup", FakeModel)
        with pytest.raises(ValueError, match="already registered"):
            registry.register_fee_model("dup", FakeModel)

    def test_missing_fee_model_raises(self):  # noqa: D102
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_fee_model("nonexistent")

    def test_missing_data_client_raises(self):  # noqa: D102
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_data_client_factory("NONEXISTENT")

    def test_missing_exec_client_raises(self):  # noqa: D102
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_exec_client_factory("NONEXISTENT")

    def test_list_names(self):  # noqa: D102
        registry = AdapterRegistry()

        class FakeModel1:
            pass

        class FakeModel2:
            pass

        registry.register_fee_model("zebra", FakeModel1)
        registry.register_fee_model("alpha", FakeModel2)
        assert registry.list_fee_model_names() == ["alpha", "zebra"]

    def test_data_client_name_case_insensitive(self):
        """Data client names are uppercased on register and lookup."""
        registry = AdapterRegistry()

        class FakeFactory:
            pass

        registry.register_data_client("massive", FakeFactory)
        assert registry.get_data_client_factory("Massive") is FakeFactory
        assert registry.get_data_client_factory("MASSIVE") is FakeFactory

    def test_get_registry_singleton(self):  # noqa: D102
        from trade_system_core.registry import get_registry  # noqa: PLC0415

        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
