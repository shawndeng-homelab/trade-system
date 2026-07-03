"""Factory for assembling the Massive.com data client on a NautilusTrader node.

Registered via :class:`nautilus_trader.config.ImportableConfig` (see the package
README); NautilusTrader instantiates the client through
:class:`MassiveLiveDataClientFactory.create` with no Nautilus source changes.
"""

import asyncio
import os
from functools import lru_cache

from massive import RESTClient
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory

from trade_system_massive.config import MassiveDataClientConfig
from trade_system_massive.constants import DEFAULT_BASE_URL
from trade_system_massive.constants import DEFAULT_BURST
from trade_system_massive.constants import DEFAULT_RATE_LIMIT_PER_MIN
from trade_system_massive.data_client import MassiveDataClient
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.instruments import MassiveInstrumentProviderConfig
from trade_system_massive.rate_limiter import TokenBucketRateLimiter
from trade_system_massive.rate_limiter import rate_per_min_to_per_sec


def resolve_api_key(config: MassiveDataClientConfig) -> str:
    """Resolve the Massive API key from config or the environment.

    Falls back to the legacy ``POLYGON_API_KEY`` variable (Massive.com is the
    rebranded Polygon.io; existing keys continue to work).

    """
    if config.api_key:
        return config.api_key
    return os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""


@lru_cache(1)
def get_cached_massive_rest_client(api_key: str, base_url: str, trace: bool) -> RESTClient:
    """Cache and return a Massive ``RESTClient`` with the given key and base URL.

    The Massive client is a stateless urllib3 pool; caching one per (key, base, trace)
    avoids re-opening connection pools across re-connects.

    """
    return RESTClient(
        api_key=api_key,
        base=base_url,
        pagination=True,
        trace=trace,
    )


@lru_cache(1)
def get_cached_massive_rate_limiter(rate_limit_per_min: float, burst: int) -> TokenBucketRateLimiter:
    """Cache and return a token-bucket limiter for the given tier settings."""
    return TokenBucketRateLimiter(
        rate=rate_per_min_to_per_sec(rate_limit_per_min),
        burst=burst,
    )


@lru_cache(1)
def get_cached_massive_instrument_provider(
    client: RESTClient,
    rate_limiter: TokenBucketRateLimiter,
    clock: LiveClock,
) -> MassiveInstrumentProvider:
    """Cache and return a Massive instrument provider (no on-start load configured).

    The factory wires ``load_all``/``load_ids`` into the returned provider's config so
    :meth:`InstrumentProvider.initialize` dispatches to the right loader.

    """
    return MassiveInstrumentProvider(
        client=client,
        rate_limiter=rate_limiter,
        clock=clock,
    )


class MassiveLiveDataClientFactory(LiveDataClientFactory):
    """Factory for :class:`MassiveDataClient` instances on a live node."""

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: MassiveDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> MassiveDataClient:
        """Create and return a new Massive data client.

        Parameters
        ----------
        loop : asyncio.AbstractEventLoop
            The event loop for the client.
        name : str
            The custom client ID.
        config : MassiveDataClientConfig
            The client configuration.
        msgbus : MessageBus
            The message bus for the client.
        cache : Cache
            The cache for the client.
        clock : LiveClock
            The clock for the client.

        Returns:
        -------
        MassiveDataClient

        """
        api_key = resolve_api_key(config)
        base_url = config.base_url or DEFAULT_BASE_URL
        rate_limit_per_min = config.rate_limit_per_min or DEFAULT_RATE_LIMIT_PER_MIN
        burst = config.burst or DEFAULT_BURST

        rest_client = get_cached_massive_rest_client(api_key, base_url, config.trace)
        rate_limiter = get_cached_massive_rate_limiter(rate_limit_per_min, burst)
        provider = get_cached_massive_instrument_provider(
            client=rest_client,
            rate_limiter=rate_limiter,
            clock=clock,
        )

        # Configure on-start loading via the base provider config so `initialize()`
        # dispatches correctly: full chain fetch only when underlyings or futures
        # product codes are set, otherwise per-id fetch for the requested instrument_ids.
        provider_config = MassiveInstrumentProviderConfig(
            load_all=bool(config.options_underlyings or config.futures_product_codes),
            load_ids=list(config.instrument_ids) if config.instrument_ids else [],
            options_underlyings=config.options_underlyings,
            pagination_limit=config.pagination_limit,
            futures_product_codes=config.futures_product_codes,
            futures_asset_class_overrides=config.futures_asset_class_overrides,
            futures_multipliers=config.futures_multipliers,
        )
        provider._config = provider_config

        return MassiveDataClient(
            loop=loop,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            name=name,
        )


__all__ = [
    "MassiveLiveDataClientFactory",
    "get_cached_massive_instrument_provider",
    "get_cached_massive_rate_limiter",
    "get_cached_massive_rest_client",
    "resolve_api_key",
]
