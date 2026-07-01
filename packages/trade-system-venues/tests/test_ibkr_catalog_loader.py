"""Tests for the IBKR catalog loader.

These exercise only import-safety and ``NAUTILUS_PATH`` resolution; the download
functions require a live TWS/Gateway and are not unit-tested here.
"""

import inspect

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from trade_system_venues.ibkr import catalog_loader


def test_module_exposes_async_helpers():
    """The module imports and exposes async download helpers."""
    assert inspect.iscoroutinefunction(catalog_loader.make_client)
    assert inspect.iscoroutinefunction(catalog_loader.download_stock_bars)
    assert inspect.iscoroutinefunction(catalog_loader.download_option_chain)


def test_default_catalog_uses_nautilus_path(monkeypatch, tmp_path):
    """default_catalog resolves the catalog under NAUTILUS_PATH."""
    monkeypatch.setenv("NAUTILUS_PATH", str(tmp_path))
    catalog = catalog_loader.default_catalog()
    assert isinstance(catalog, ParquetDataCatalog)


def test_default_catalog_requires_nautilus_path(monkeypatch):
    """default_catalog raises when NAUTILUS_PATH is unset."""
    monkeypatch.delenv("NAUTILUS_PATH", raising=False)
    with pytest.raises(OSError, match="NAUTILUS_PATH"):
        catalog_loader.default_catalog()
