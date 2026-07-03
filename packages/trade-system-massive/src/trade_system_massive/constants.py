"""Constants for the Massive.com data adapter."""

from typing import Final

from nautilus_trader.model.identifiers import ClientId


MASSIVE: Final[str] = "MASSIVE"
MASSIVE_CLIENT_ID: Final[ClientId] = ClientId(MASSIVE)

# Massive.com is the rebranded Polygon.io REST/WebSocket API (2025-10-30).
DEFAULT_BASE_URL: Final[str] = "https://api.massive.com"

# Conservative defaults for the free pricing tier (Polygon free = 5 calls/min).
# Override via MassiveDataClientConfig for paid tiers.
DEFAULT_RATE_LIMIT_PER_MIN: Final[float] = 5.0
DEFAULT_BURST: Final[int] = 5

# Pagination page size used for historical trades/quotes/aggs requests.
DEFAULT_PAGE_LIMIT: Final[int] = 50_000

# Massive option tickers are prefixed with "O:"; equities are bare (or "S:").
OPTION_TICKER_PREFIX: Final[str] = "O:"

# Venue used for US equity options (all US options route through OPRA).
OPTION_VENUE: Final[str] = "OPRA"

# Default venue for a futures contract when Massive reports no `trading_venue`.
# XCBT (CME/CBOT) is the most common; override per-instrument from contract data.
DEFAULT_FUTURES_VENUE: Final[str] = "XCBT"
