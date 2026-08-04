"""Integration tests against the real EODHD API.

These tests are skipped automatically when ``EODHD_API_KEY`` is not set.
They exist to catch schema drift between the package and EODHD's actual
response; they should not run in CI without a key.
"""

import os
from datetime import date

import pytest
from earnings_datasource import EodhdEarningsProvider


@pytest.mark.skipif(
    not os.environ.get("EODHD_API_KEY"),
    reason="EODHD_API_KEY not set; skipping real-API integration test",
)
def test_real_fetch_aapl_recent_quarter() -> None:
    """Fetch a recent quarter of AAPL earnings and validate the shape."""
    provider = EodhdEarningsProvider()
    # Use a date range that should cover at least one AAPL earnings event.
    events = provider.fetch(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))
    assert len(events) >= 1, "expected at least one AAPL earnings event in 2024"
    for ev in events:
        assert ev.symbol == "AAPL"
        assert ev.code == "AAPL.US"
        assert ev.report_date.tzinfo is not None
        # session must be one of the four literal values.
        assert ev.session in {"bmo", "amc", "intraday", "unknown"}
        # If both estimate and actual are present, surprise is computed.
        if ev.actual_eps is not None and ev.estimate_eps is not None:
            assert ev.eps_surprise is not None
