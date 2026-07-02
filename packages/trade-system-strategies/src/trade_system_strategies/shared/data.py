"""Catalog IO conveniences for strategies and research.

Thin wrappers around ``trade_system_venues.ibkr.catalog_loader`` so strategy code and
notebooks share one path to the shared ``ParquetDataCatalog`` (rooted at
``$NAUTILUS_PATH``).
"""



from trade_system_venues.ibkr import catalog_loader as _cl


def default_catalog():
    """Return the shared ``ParquetDataCatalog`` at ``$NAUTILUS_PATH/catalog``."""
    return _cl.default_catalog()


def load_option_instruments(underlying: str | None = None) -> list:
    """Return option instruments from the catalog, optionally filtered by underlying."""
    catalog = default_catalog()
    instruments = [i for i in catalog.instruments() if i.type_name == "OptionContract"]
    if underlying is None:
        return instruments
    return [i for i in instruments if str(i.underlying) == underlying]
