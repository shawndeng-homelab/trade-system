"""optopsy plugin entry point for the EODHD earnings provider.

Registers a :class:`optopsy.data.providers.base.DataProvider` subclass
exposing a single chat-UI tool ``fetch_earnings_calendar``.

If optopsy is not installed, ``register()`` returns ``None`` so optopsy
silently skips this entry point rather than blowing up at import time.
This keeps ``earnings_datasource`` usable as a standalone library and
limits optopsy to an optional integration.

The entry point is wired in ``pyproject.toml``::

    [project.entry-points."optopsy.providers"]
    earnings_eodhd = "earnings_datasource.entry_point:register"
"""

import logging
import os
from datetime import date
from typing import Any

from earnings_datasource.models import EarningsCalendar
from earnings_datasource.providers.eodhd import EodhdEarningsProvider


logger = logging.getLogger(__name__)


def register() -> Any:
    """Entry-point callable.

    Returns the adapter class for optopsy to instantiate, or ``None`` if
    optopsy is not installed.
    """
    try:
        from optopsy.data.providers.base import DataProvider  # noqa: PLC0415 - lazy import; optopsy is optional
    except ImportError:
        logger.info(
            "optopsy is not installed; earnings_datasource optopsy entry point disabled. "
            "Install with `uv add optopsy[data]` to enable."
        )
        return None

    class EodhdEarningsAdapter(DataProvider):
        """optopsy DataProvider adapter for the EODHD earnings calendar."""

        @property
        def name(self) -> str:
            return "EODHD Earnings"

        @property
        def env_key(self) -> str:
            return "EODHD_API_KEY"

        def is_available(self) -> bool:  # type: ignore[override]
            return bool(os.environ.get(self.env_key))

        @property
        def replaces_dataset(self) -> bool:  # type: ignore[override]
            return False

        def get_tool_names(self) -> list[str]:  # type: ignore[override]
            return ["fetch_earnings_calendar"]

        def get_tool_schemas(self) -> list[dict[str, Any]]:  # type: ignore[override]
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "fetch_earnings_calendar",
                        "description": (
                            "Fetch the EODHD earnings calendar for one or more symbols. "
                            "Returns a DataFrame of upcoming/past earnings announcements "
                            "with EPS/revenue estimates, actuals, and BMO/AMC timing."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "symbols": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "Tickers to fetch (e.g. ['AAPL', 'MSFT']). "
                                        "Bare tickers default to the US exchange."
                                    ),
                                },
                                "start_date": {
                                    "type": "string",
                                    "description": "Inclusive start date (YYYY-MM-DD).",
                                },
                                "end_date": {
                                    "type": "string",
                                    "description": "Inclusive end date (YYYY-MM-DD).",
                                },
                            },
                            "required": ["symbols", "start_date", "end_date"],
                        },
                    },
                }
            ]

        def execute(  # type: ignore[override]
            self, tool_name: str, arguments: dict[str, Any]
        ) -> tuple[str, Any]:
            if tool_name != "fetch_earnings_calendar":
                return f"Unknown tool: {tool_name}", None
            symbols = arguments.get("symbols") or []
            start = arguments.get("start_date")
            end = arguments.get("end_date")
            if not symbols or not start or not end:
                return (
                    "fetch_earnings_calendar requires `symbols`, `start_date`, and `end_date`.",
                    None,
                )
            try:
                provider = EodhdEarningsProvider()
                events = provider.fetch(
                    symbols=symbols,
                    start_date=date.fromisoformat(start),
                    end_date=date.fromisoformat(end),
                )
            except Exception as exc:
                return f"Failed to fetch earnings: {exc}", None
            df = EarningsCalendar(events=events, source="eodhd").to_dataframe()
            return f"Fetched {len(events)} earnings events.", df

    return EodhdEarningsAdapter
