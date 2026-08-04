"""Tests for the Pydantic models in earnings_datasource.models."""

from datetime import UTC
from datetime import datetime

import pandas as pd
import pytest
from earnings_datasource.models import EarningsCalendar
from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from pydantic import ValidationError


def test_minimal_event_required_fields_only() -> None:
    """Only ``code`` and ``report_date`` are required."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
    )
    assert ev.code == "AAPL.US"
    assert ev.symbol == "AAPL"  # derived
    assert ev.session == "amc"  # 17:00 ET is AMC


def test_event_frozen() -> None:
    """Assignment to a frozen model raises ValidationError."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        ev.code = "MSFT.US"  # type: ignore[misc]


def test_event_symbol_derived_from_code() -> None:
    """``symbol`` is split off the first ``.`` of ``code``."""
    ev = EarningsEvent(
        code="BMW.XETRA",
        report_date=datetime(2024, 8, 1, 12, 0, tzinfo=UTC),
    )
    assert ev.symbol == "BMW"

    ev2 = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 12, 0, tzinfo=UTC),
    )
    assert ev2.symbol == "AAPL"


def test_event_explicit_symbol_wins() -> None:
    """If the caller supplies ``symbol`` explicitly, it is preserved."""
    ev = EarningsEvent(
        code="BRK.B.US",
        symbol="BRK-B",
        report_date=datetime(2024, 8, 1, 12, 0, tzinfo=UTC),
    )
    assert ev.symbol == "BRK-B"


def test_session_bmo() -> None:
    """Pre-open wire time -> ``bmo``."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 11, 0, tzinfo=UTC),  # 07:00 ET
    )
    assert ev.session == "bmo"


def test_session_amc() -> None:
    """Post-close wire time -> ``amc``."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),  # 17:00 ET
    )
    assert ev.session == "amc"


def test_session_intraday() -> None:
    """Mid-day wire time -> ``intraday``."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 15, 0, tzinfo=UTC),  # 11:00 ET
    )
    assert ev.session == "intraday"


def test_eps_surprise_computed() -> None:
    """``actual_eps - estimate_eps`` is auto-derived."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        estimate_eps=1.0,
        actual_eps=1.2,
    )
    assert ev.eps_surprise == pytest.approx(0.2)


def test_eps_surprise_none_when_missing() -> None:
    """Missing actual or estimate -> ``eps_surprise`` is ``None``."""
    a = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        estimate_eps=1.0,
    )
    assert a.eps_surprise is None
    b = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        actual_eps=1.2,
    )
    assert b.eps_surprise is None


def test_revenue_surprise_computed() -> None:
    """``actual_revenue - estimate_revenue`` is auto-derived."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        estimate_revenue=100.0,
        actual_revenue=120.5,
    )
    assert ev.revenue_surprise == pytest.approx(20.5)


def test_fiscal_period_derived() -> None:
    """``fiscal_year`` + ``fiscal_quarter`` produce ``"YYYYQN"`` string."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        fiscal_year=2024,
        fiscal_quarter=3,
    )
    assert ev.fiscal_period == "2024Q3"


def test_fiscal_period_none_when_year_missing() -> None:
    """Missing fiscal year leaves ``fiscal_period`` as ``None``."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        fiscal_quarter=3,
    )
    assert ev.fiscal_period is None


def test_calendar_to_dataframe_columns() -> None:
    """DataFrame has the canonical column order."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 0, tzinfo=UTC),
        estimate_eps=1.0,
        actual_eps=1.2,
    )
    df = EarningsCalendar(events=[ev]).to_dataframe()
    assert list(df.columns) == [
        "code",
        "symbol",
        "report_date",
        "report_date_utc",
        "fiscal_year",
        "fiscal_quarter",
        "fiscal_period",
        "session",
        "before_market_open",
        "after_market_close",
        "estimate_eps",
        "actual_eps",
        "eps_surprise",
        "estimate_revenue",
        "actual_revenue",
        "revenue_surprise",
        "currency",
        "period",
        "source",
    ]


def test_calendar_to_dataframe_empty() -> None:
    """Empty events list returns an empty DataFrame with the right columns."""
    df = EarningsCalendar(events=[]).to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert "code" in df.columns
    assert "report_date" in df.columns


def test_calendar_to_dataframe_report_date_normalized() -> None:
    """``report_date`` is tz-naive midnight UTC; ``report_date_utc`` is full."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date=datetime(2024, 8, 1, 21, 30, 45, tzinfo=UTC),
    )
    df = EarningsCalendar(events=[ev]).to_dataframe()
    # ``report_date`` is tz-naive at UTC midnight.
    rd = df["report_date"].iloc[0]
    assert pd.isna(rd.tzinfo)
    assert rd.hour == 0 and rd.minute == 0 and rd.second == 0
    # ``report_date_utc`` is tz-aware with the full time.
    rd_utc = df["report_date_utc"].iloc[0]
    assert rd_utc.tzinfo is not None
    assert rd_utc.hour == 21 and rd_utc.minute == 30


def test_provider_error_is_exception() -> None:
    """``EarningsProviderError`` is a catchable Exception."""
    assert issubclass(EarningsProviderError, Exception)
    with pytest.raises(EarningsProviderError):
        raise EarningsProviderError("boom")


def test_report_date_iso_string_parsed() -> None:
    """``report_date`` accepts an ISO 8601 string with ``+00:00`` offset."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-08-01T21:00:00+00:00",  # type: ignore[arg-type]
    )
    assert ev.report_date.tzinfo is not None
    assert ev.report_date.hour == 21


def test_report_date_iso_string_with_z_suffix() -> None:
    """``report_date`` accepts ISO 8601 strings with the ``Z`` suffix."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-08-01T21:00:00Z",  # type: ignore[arg-type]
    )
    assert ev.report_date.tzinfo is not None
    assert ev.report_date.hour == 21
