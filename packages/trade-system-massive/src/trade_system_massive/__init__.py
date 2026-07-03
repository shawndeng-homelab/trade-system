"""NautilusTrader data adapter for the Massive.com (rebranded Polygon.io) API.

Massive.com is the rebranded Polygon.io REST/WebSocket API (2025-10-30). Existing
Polygon API keys and accounts continue to work unchanged.

v1 provides historical REST access (trade ticks, quote ticks, bars, instrument
definitions, and last-quote order-book snapshots); real-time WebSocket streaming is
planned for v2.
"""

from trade_system_massive.config import MassiveDataClientConfig
from trade_system_massive.constants import MASSIVE
from trade_system_massive.data_client import MassiveDataClient
from trade_system_massive.factories import MassiveLiveDataClientFactory
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.instruments import MassiveInstrumentProviderConfig


__all__ = [
    "MASSIVE",
    "MassiveDataClient",
    "MassiveDataClientConfig",
    "MassiveInstrumentProvider",
    "MassiveInstrumentProviderConfig",
    "MassiveLiveDataClientFactory",
]
