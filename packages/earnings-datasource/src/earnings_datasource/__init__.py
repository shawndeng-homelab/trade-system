"""Earnings calendar data source for optopsy-based options backtests.

Quick start::

    from earnings_datasource import EodhdEarningsProvider, EarningsCalendar
    from earnings_datasource.providers.store import merge_earnings
    from datetime import date

    provider = EodhdEarningsProvider()  # uses EODHD_API_KEY env var
    events = provider.fetch(["AAPL", "MSFT"], date(2024, 1, 1), date(2024, 3, 31))
    df = EarningsCalendar(events=events).to_dataframe()
    merge_earnings("AAPL.US", df, dedup_cols=["code", "report_date_utc"])
"""

from earnings_datasource.models import EarningsCalendar
from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from earnings_datasource.providers.base import BaseEarningsProvider
from earnings_datasource.providers.eodhd import EodhdEarningsProvider


__all__ = [
    "BaseEarningsProvider",
    "EarningsCalendar",
    "EarningsEvent",
    "EarningsProviderError",
    "EodhdEarningsProvider",
]
