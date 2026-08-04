"""Tests for the Pydantic models in earnings_datasource.models."""

from datetime import UTC
from datetime import date as date_cls
from datetime import datetime

import pandas as pd
import pytest
from earnings_datasource.models import EarningsCalendar
from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from pydantic import ValidationError


# ── EarningsEvent construction ────────────────────────────────────────────


def test_minimal_event_required_fields_only() -> None:
    """Only ``code`` and ``report_date`` are required."""
    ev = EarningsEvent(code="AAPL.US", report_date="2024-02-01")  # type: ignore[arg-type]
    assert ev.code == "AAPL.US"
    assert ev.symbol == "AAPL"  # derived
    assert ev.source == "eodhd"


def test_event_frozen() -> None:
    """Assignment to a frozen model raises ValidationError."""
    ev = EarningsEvent(code="AAPL.US", report_date=datetime(2024, 2, 1, tzinfo=UTC))
    with pytest.raises(ValidationError):
        ev.code = "MSFT.US"  # type: ignore[misc]


def test_event_symbol_derived_from_code() -> None:
    """``symbol`` is split off the first ``.`` of ``code``."""
    ev = EarningsEvent(code="BMW.XETRA", report_date=datetime(2024, 2, 1, tzinfo=UTC))
    assert ev.symbol == "BMW"

    ev2 = EarningsEvent(code="AAPL.US", report_date=datetime(2024, 2, 1, tzinfo=UTC))
    assert ev2.symbol == "AAPL"


def test_event_explicit_symbol_wins() -> None:
    """If the caller supplies ``symbol`` explicitly, it is preserved."""
    ev = EarningsEvent(
        code="BRK.B.US",
        symbol="BRK-B",
        report_date=datetime(2024, 2, 1, tzinfo=UTC),
    )
    assert ev.symbol == "BRK-B"


# ── Session derivation from before_after_market ───────────────────────────


def test_session_bmo_from_beforemarket() -> None:
    """``BeforeMarket`` label -> ``bmo`` session."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        before_after_market="BeforeMarket",
    )
    assert ev.session == "bmo"


def test_session_amc_from_aftermarket() -> None:
    """``AfterMarket`` label -> ``amc`` session."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        before_after_market="AfterMarket",
    )
    assert ev.session == "amc"


def test_session_unknown_when_label_missing() -> None:
    """No ``before_after_market`` -> ``unknown`` session."""
    ev = EarningsEvent(code="AAPL.US", report_date="2024-02-01")  # type: ignore[arg-type]
    assert ev.session == "unknown"


def test_session_legacy_aliases() -> None:
    """``bmo`` / ``amc`` and ``premarket`` / ``postmarket`` aliases are accepted."""
    for label, expected in [
        ("bmo", "bmo"),
        ("amc", "amc"),
        ("premarket", "bmo"),
        ("postmarket", "amc"),
        ("BMO", "bmo"),  # case-insensitive
        (" AfterMarket ", "amc"),  # whitespace trimmed
    ]:
        ev = EarningsEvent(
            code="AAPL.US",
            report_date="2024-02-01",  # type: ignore[arg-type]
            before_after_market=label,
        )
        assert ev.session == expected, f"label={label!r} -> {ev.session}"


# ── EPS surprise + percent ────────────────────────────────────────────────


def test_eps_surprise_computed() -> None:
    """``actual_eps - estimate_eps`` is auto-derived."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        estimate_eps=1.0,
        actual_eps=1.2,
    )
    assert ev.eps_surprise == pytest.approx(0.2)


def test_eps_surprise_none_when_missing() -> None:
    """Missing actual or estimate -> ``eps_surprise`` is ``None``."""
    a = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        estimate_eps=1.0,
    )
    assert a.eps_surprise is None
    b = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        actual_eps=1.2,
    )
    assert b.eps_surprise is None


def test_eps_surprise_pct_from_percent() -> None:
    """EODHD ``percent=3.3175`` -> ``eps_surprise_pct=0.033175`` (fraction)."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        estimate_eps=2.11,
        actual_eps=2.18,
        percent=3.3175,
    )
    assert ev.eps_surprise_pct == pytest.approx(0.033175)


def test_eps_surprise_pct_explicit_fraction() -> None:
    """Passing ``eps_surprise_pct`` directly is honored as a fraction."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        estimate_eps=1.0,
        actual_eps=1.05,
        eps_surprise_pct=0.05,
    )
    assert ev.eps_surprise_pct == pytest.approx(0.05)


def test_eps_surprise_pct_none_when_no_estimate() -> None:
    """No estimate -> no percent (percent is meaningless without both sides)."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        actual_eps=1.2,
        percent=10.0,
    )
    assert ev.eps_surprise_pct is None


# ── fiscal_period_end ────────────────────────────────────────────────────


def test_fiscal_period_end_parsed_from_string() -> None:
    """``fiscal_period_end`` accepts a YYYY-MM-DD string."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        fiscal_period_end="2023-12-31",  # type: ignore[arg-type]
    )
    assert ev.fiscal_period_end == date_cls(2023, 12, 31)


def test_fiscal_period_end_optional() -> None:
    """``fiscal_period_end`` is optional; defaults to ``None``."""
    ev = EarningsEvent(code="AAPL.US", report_date="2024-02-01")  # type: ignore[arg-type]
    assert ev.fiscal_period_end is None


# ── Calendar / DataFrame ──────────────────────────────────────────────────


def test_calendar_to_dataframe_columns() -> None:
    """DataFrame has the canonical column order."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
        estimate_eps=2.11,
        actual_eps=2.18,
        before_after_market="AfterMarket",
    )
    df = EarningsCalendar(events=[ev]).to_dataframe()
    assert list(df.columns) == [
        "code",
        "symbol",
        "report_date",
        "report_date_utc",
        "fiscal_period_end",
        "session",
        "estimate_eps",
        "actual_eps",
        "eps_surprise",
        "eps_surprise_pct",
        "currency",
        "source",
    ]


def test_calendar_to_dataframe_empty() -> None:
    """Empty events list returns an empty DataFrame with the right columns."""
    df = EarningsCalendar(events=[]).to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert "code" in df.columns
    assert "report_date" in df.columns


def test_calendar_to_dataframe_report_date_naive() -> None:
    """``report_date`` is tz-naive midnight UTC; ``report_date_utc`` is tz-aware."""
    ev = EarningsEvent(
        code="AAPL.US",
        report_date="2024-02-01",  # type: ignore[arg-type]
    )
    df = EarningsCalendar(events=[ev]).to_dataframe()
    rd = df["report_date"].iloc[0]
    assert pd.isna(rd.tzinfo)
    assert rd.year == 2024 and rd.month == 2 and rd.day == 1
    rd_utc = df["report_date_utc"].iloc[0]
    assert rd_utc.tzinfo is not None
    assert rd_utc.year == 2024 and rd_utc.month == 2 and rd_utc.day == 1


# ── Error type ────────────────────────────────────────────────────────────


def test_provider_error_is_exception() -> None:
    """``EarningsProviderError`` is a catchable Exception."""
    assert issubclass(EarningsProviderError, Exception)
    with pytest.raises(EarningsProviderError):
        raise EarningsProviderError("boom")
