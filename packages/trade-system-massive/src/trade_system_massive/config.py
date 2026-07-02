"""Configuration for the Massive.com data client."""

from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.model.identifiers import InstrumentId


class MassiveDataClientConfig(LiveDataClientConfig, frozen=True):
    """Configuration for ``MassiveDataClient`` instances.

    The Massive.com API is the rebranded Polygon.io API. Existing Polygon API
    keys and accounts continue to work unchanged.

    Parameters
    ----------
    api_key : str, optional
        The Massive.com API key. If ``None`` then the ``MASSIVE_API_KEY``
        (or legacy ``POLYGON_API_KEY``) environment variable is used.
    base_url : str, optional
        The REST base URL override. Defaults to ``https://api.massive.com``.
    rate_limit_per_min : float, default 5.0
        The sustained request rate budget in calls per minute. The free tier is
        rate-limited; raise this for paid tiers. Used by the token-bucket
        limiter that gates every REST call.
    burst : int, default 5
        The maximum number of calls that may be dispatched in an instantaneous
        burst before the sustained rate is enforced.
    max_retries : int, default 3
        The maximum number of retries on HTTP 429 (rate limited) responses.
    pagination_limit : int, default 50000
        The page size passed to paginated endpoints. With ``pagination=True``
        (the client default) this controls page size, not total results.
    trace : bool, default False
        If request/response diagnostics should be printed by the underlying
        Massive client (equivalent to ``RESTClient(trace=True)``).
    bars_timestamp_on_close : bool, default True
        If bar data should be timestamped on the close (True) or open (False)
        of the bar period.
    instrument_ids : list[InstrumentId], optional
        The instrument IDs to load definitions for on start.
    options_underlyings : set[str], optional
        The equity underlyings whose option chains to preload on start.

    """

    api_key: str | None = None
    base_url: str | None = None
    rate_limit_per_min: float = 5.0
    burst: int = 5
    max_retries: int = 3
    pagination_limit: int = 50_000
    trace: bool = False
    bars_timestamp_on_close: bool = True
    instrument_ids: list[InstrumentId] | None = None
    options_underlyings: set[str] | None = None
