"""Abstract base class for earnings-calendar providers.

A provider is a thin client around an external data source (EODHD today;
potentially Unusual Whales, SEC EDGAR, FMP, etc. in the future) that
normalizes its raw response into a flat list of :class:`EarningsEvent`.
"""

from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import ClassVar

from earnings_datasource.models import EarningsEvent


class BaseEarningsProvider(ABC):
    """Abstract base class for earnings-calendar providers.

    Attributes:
        source_name: Short identifier for the underlying data source
            (e.g. ``"eodhd"``). Used in cache file names and logs.
    """

    source_name: ClassVar[str]

    @abstractmethod
    def fetch(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> list[EarningsEvent]:
        """Fetch and normalize earnings events.

        Args:
            symbols: Tickers to fetch. May be bare (``AAPL``) or vendor-native
                (``AAPL.US``); call :meth:`normalize_symbol` to canonicalize.
            start_date: Inclusive start of the announcement-date window.
            end_date: Inclusive end of the announcement-date window.

        Returns:
            A flat list of normalized :class:`EarningsEvent` records. May
            be shorter than the requested range if the vendor has no data
            for those symbols/dates.
        """

    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """Canonicalize a user-supplied ticker into the vendor's native form.

        For EODHD this appends ``.US`` to bare tickers. Implementations
        should be idempotent: ``normalize_symbol(normalize_symbol(x)) == normalize_symbol(x)``.
        """

    @abstractmethod
    def cache_key(self, symbol: str) -> str:
        """Return the parquet cache filename (sans extension) for a ticker.

        Usually identical to :meth:`normalize_symbol` but kept separate
        so the two concerns can evolve independently.
        """
