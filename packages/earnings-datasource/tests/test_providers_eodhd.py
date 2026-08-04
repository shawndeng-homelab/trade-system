"""Tests for EodhdEarningsProvider.

HTTP calls are mocked via a custom ``MockSession`` that returns canned
JSON responses, so no real EODHD requests are issued during tests.
"""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import requests
from earnings_datasource import EarningsCalendar
from earnings_datasource import EodhdEarningsProvider
from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from earnings_datasource.providers import eodhd as eodhd_mod
from earnings_datasource.providers.store import write_earnings


# ── Mock session ──────────────────────────────────────────────────────────


class _MockResponse:
    def __init__(self, status_code: int, payload: Any, url: str = "https://eodhd.com/api/calendar/earnings") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else json.dumps(payload)
        self.url = url
        self.reason = {200: "OK", 429: "Too Many Requests", 500: "Internal Server Error"}.get(status_code, "Error")

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code}")
            err.response = self  # type: ignore[attr-defined]
            raise err


class _MockSession:
    """Records every call and replays a scripted sequence of responses."""

    def __init__(self, script: list[_MockResponse]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict | None = None, timeout: int | None = None) -> _MockResponse:
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if not self._script:
            msg = "MockSession: no scripted response left"
            raise RuntimeError(msg)
        return self._script.pop(0)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def monkeypatch_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the EODHD_API_KEY env var is set for the test."""
    monkeypatch.setenv("EODHD_API_KEY", "test-key-12345")


# ── Tests: symbol normalization ──────────────────────────────────────────


def test_normalize_symbol_appends_us(monkeypatch_api_key: None) -> None:
    """Bare tickers get ``.US`` appended; case and whitespace are normalized."""
    p = EodhdEarningsProvider()
    assert p.normalize_symbol("AAPL") == "AAPL.US"
    assert p.normalize_symbol("aapl") == "AAPL.US"  # case insensitive
    assert p.normalize_symbol(" AAPL ") == "AAPL.US"  # whitespace trimmed


def test_normalize_symbol_preserves_existing_suffix(monkeypatch_api_key: None) -> None:
    """Tickers that already carry an exchange suffix pass through unchanged."""
    p = EodhdEarningsProvider()
    assert p.normalize_symbol("AAPL.US") == "AAPL.US"
    assert p.normalize_symbol("BMW.XETRA") == "BMW.XETRA"
    assert p.normalize_symbol("VOD.LSE") == "VOD.LSE"


def test_cache_key_matches_normalize(monkeypatch_api_key: None) -> None:
    """``cache_key`` returns the same value as ``normalize_symbol``."""
    p = EodhdEarningsProvider()
    assert p.cache_key("AAPL") == p.normalize_symbol("AAPL")


# ── Tests: normalize ────────────────────────────────────────────────────


def test_normalize_eodhd_paid_plan_row() -> None:
    """A real EODHD paid-plan row normalizes to an EarningsEvent."""
    raw = {
        "code": "AAPL.US",
        "report_date": "2024-02-01",
        "date": "2023-12-31",
        "before_after_market": "AfterMarket",
        "currency": "USD",
        "actual": 2.18,
        "estimate": 2.11,
        "difference": 0.07,
        "percent": 3.3175,
    }
    events = eodhd_mod._normalize_rows([raw])
    assert len(events) == 1
    ev = events[0]
    assert ev.code == "AAPL.US"
    assert ev.symbol == "AAPL"
    assert ev.session == "amc"
    assert ev.actual_eps == 2.18
    assert ev.estimate_eps == 2.11
    assert ev.eps_surprise == pytest.approx(0.07)
    assert ev.eps_surprise_pct == pytest.approx(0.033175)
    assert ev.fiscal_period_end == date(2023, 12, 31)
    assert ev.currency == "USD"


def test_normalize_skips_incomplete_rows() -> None:
    """Rows missing both ``code`` and ``report_date`` are skipped."""
    rows = [
        {"code": "AAPL.US", "report_date": "2024-02-01", "actual": 1.0},
        {"code": None, "report_date": "2024-02-01"},
        {"code": "MSFT.US", "report_date": None},
    ]
    events = eodhd_mod._normalize_rows(rows)
    assert len(events) == 1
    assert events[0].code == "AAPL.US"


def test_extract_earnings_list_from_dict() -> None:
    """Paid-plan payload wraps the array in ``{"earnings": [...]}``."""
    payload = {
        "type": "Earnings",
        "from": "2024-01-01",
        "to": "2024-01-30",
        "earnings": [{"code": "AAPL.US", "report_date": "2024-02-01"}],
    }
    assert eodhd_mod._extract_earnings_list(payload) == [{"code": "AAPL.US", "report_date": "2024-02-01"}]


def test_extract_earnings_list_from_bare_list() -> None:
    """A bare list payload is returned as-is (defensive)."""
    payload = [{"code": "AAPL.US", "report_date": "2024-02-01"}]
    assert eodhd_mod._extract_earnings_list(payload) == payload


def test_extract_earnings_list_error_payload_raises() -> None:
    """An error payload without an ``earnings`` list raises."""
    with pytest.raises(EarningsProviderError, match="error payload"):
        eodhd_mod._extract_earnings_list({"error": "rate limited"})


def test_extract_earnings_list_unexpected_shape_raises() -> None:
    """A scalar payload raises ``EarningsProviderError``."""
    with pytest.raises(EarningsProviderError, match="unexpected"):
        eodhd_mod._extract_earnings_list("not a list or dict")


# ── Tests: fetch ─────────────────────────────────────────────────────────


def test_fetch_wrapped_response(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a wrapped ``{"earnings": [...]}`` response is parsed correctly."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    raw_payload = {
        "type": "Earnings",
        "from": "2024-02-01",
        "to": "2024-02-28",
        "earnings": [
            {
                "code": "AAPL.US",
                "report_date": "2024-02-01",
                "date": "2023-12-31",
                "before_after_market": "AfterMarket",
                "currency": "USD",
                "actual": 2.18,
                "estimate": 2.11,
                "percent": 3.3175,
            }
        ],
    }
    session = _MockSession([_MockResponse(200, raw_payload)])
    p = EodhdEarningsProvider(session=session)
    events = p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))
    assert len(events) == 1
    assert events[0].code == "AAPL.US"
    assert events[0].actual_eps == 2.18
    assert events[0].session == "amc"


def test_fetch_sends_api_token(monkeypatch_api_key: None) -> None:
    """The provider sends ``api_token=...`` in the query string."""
    # A 31-day January range splits into 2 windows (1-30, 31).
    session = _MockSession([_MockResponse(200, []), _MockResponse(200, [])])
    p = EodhdEarningsProvider(api_key="my-key", session=session)
    p.fetch(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))
    assert session.calls[0]["params"]["api_token"] == "my-key"


def test_fetch_filters_by_symbol(monkeypatch_api_key: None) -> None:
    """Events for other symbols in the response are filtered out client-side."""
    raw = [
        {"code": "AAPL.US", "type": "eps", "report_date": "2024-02-01T21:00:00+00:00", "actual": 1.0},
        {"code": "MSFT.US", "type": "eps", "report_date": "2024-02-01T21:00:00+00:00", "actual": 2.0},
    ]
    session = _MockSession([_MockResponse(200, raw)])
    p = EodhdEarningsProvider(session=session)
    events = p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))
    assert [e.code for e in events] == ["AAPL.US"]


def test_fetch_retries_on_429(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 is retried; the second 200 is returned."""
    # Skip throttle sleep to keep the test fast.
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(eodhd_mod, "_BACKOFF_FACTOR", 1.0)
    raw = [
        {"code": "AAPL.US", "type": "eps", "report_date": "2024-02-01T21:00:00+00:00", "actual": 1.0},
    ]
    session = _MockSession(
        [
            _MockResponse(429, None),
            _MockResponse(429, None),
            _MockResponse(200, raw),
        ]
    )
    p = EodhdEarningsProvider(session=session)
    events = p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))
    assert len(events) == 1
    assert len(session.calls) == 3  # two 429s, then the success


def test_fetch_raises_after_max_retries(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """After 5 consecutive 5xx, ``fetch`` raises ``EarningsProviderError``."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(eodhd_mod, "_BACKOFF_FACTOR", 1.0)
    session = _MockSession([_MockResponse(500, None) for _ in range(5)])
    p = EodhdEarningsProvider(session=session)
    with pytest.raises(EarningsProviderError, match="gave up"):
        p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))


def test_fetch_raises_on_4xx(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-retryable 4xx raises immediately with a redacted URL in the message."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    session = _MockSession(
        [_MockResponse(403, None, url="https://eodhd.com/api/calendar/earnings?api_token=secret&fmt=json")]
    )
    p = EodhdEarningsProvider(api_key="secret", session=session)
    with pytest.raises(EarningsProviderError) as excinfo:
        p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))
    # Token must not appear in the error message.
    assert "secret" not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_fetch_pagination_by_month(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 91-day window (across Feb 2024 leap year) issues 4 HTTP calls."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    responses = [_MockResponse(200, []) for _ in range(4)]
    session = _MockSession(responses)
    p = EodhdEarningsProvider(session=session)
    p.fetch(["AAPL"], date(2024, 1, 1), date(2024, 3, 31))  # ~91 days
    assert len(session.calls) == 4
    # The first window starts 2024-01-01; the fourth ends 2024-03-31.
    from_params = [c["params"]["from"] for c in session.calls]
    to_params = [c["params"]["to"] for c in session.calls]
    assert from_params == ["2024-01-01", "2024-01-31", "2024-03-01", "2024-03-31"]
    assert to_params == ["2024-01-30", "2024-02-29", "2024-03-30", "2024-03-31"]


def test_fetch_invalid_date_range(monkeypatch_api_key: None) -> None:
    """Start > end raises immediately."""
    session = _MockSession([])
    p = EodhdEarningsProvider(session=session)
    with pytest.raises(EarningsProviderError, match="after end_date"):
        p.fetch(["AAPL"], date(2024, 3, 1), date(2024, 2, 1))


def test_fetch_non_json_response(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 with non-JSON body keeps retrying; after max retries it raises."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(eodhd_mod, "_BACKOFF_FACTOR", 1.0)

    class _BadJSONResponse(_MockResponse):
        def json(self) -> Any:
            raise ValueError("not JSON")

    session = _MockSession([_BadJSONResponse(200, "garbage") for _ in range(5)])
    p = EodhdEarningsProvider(session=session)
    with pytest.raises(EarningsProviderError, match="gave up"):
        p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))


# ── Tests: token redaction ───────────────────────────────────────────────


def test_redact_token_strips_value() -> None:
    """The ``api_token`` value is replaced with ``***``."""
    url = "https://eodhd.com/api/calendar/earnings?api_token=secret123&fmt=json"
    redacted = eodhd_mod._redact_token(url)
    assert "secret123" not in redacted
    assert "api_token=***" in redacted


def test_redact_token_handles_path_segments() -> None:
    """A ``api_token``-looking segment in the path is left alone."""
    url = "https://eodhd.com/api_token_in_path/calendar/earnings?api_token=secret"
    redacted = eodhd_mod._redact_token(url)
    assert "api_token_in_path" in redacted
    assert "secret" not in redacted


def test_redact_token_handles_backup_token() -> None:
    """A ``backup_api_token`` is left untouched (only the first match is replaced)."""
    url = "https://eodhd.com/api/calendar/earnings?backup_api_token=keep&api_token=secret"
    redacted = eodhd_mod._redact_token(url)
    assert "backup_api_token=keep" in redacted
    assert "api_token=***" in redacted


# ── Tests: month windows ─────────────────────────────────────────────────


def test_month_windows_single() -> None:
    """A 15-day span fits in a single window."""
    windows = eodhd_mod._month_windows(date(2024, 1, 1), date(2024, 1, 15))
    assert windows == [(date(2024, 1, 1), date(2024, 1, 15))]


def test_month_windows_padded() -> None:
    """A 91-day span (across Feb 2024 leap year) splits into 4 non-overlapping windows."""
    windows = eodhd_mod._month_windows(date(2024, 1, 1), date(2024, 3, 31))
    assert len(windows) == 4
    assert windows[0] == (date(2024, 1, 1), date(2024, 1, 30))
    assert windows[1] == (date(2024, 1, 31), date(2024, 2, 29))
    assert windows[2] == (date(2024, 3, 1), date(2024, 3, 30))
    assert windows[3] == (date(2024, 3, 31), date(2024, 3, 31))


def test_month_windows_inverted_returns_empty() -> None:
    """An inverted range (start > end) returns an empty list, not an error."""
    assert eodhd_mod._month_windows(date(2024, 3, 1), date(2024, 1, 1)) == []


def test_month_windows_exact_30_days() -> None:
    """A 30-day span is one window, not two."""
    windows = eodhd_mod._month_windows(date(2024, 1, 1), date(2024, 1, 30))
    assert windows == [(date(2024, 1, 1), date(2024, 1, 30))]


# ── Tests: instantiation ─────────────────────────────────────────────────


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructor raises when neither ``api_key`` nor the env var is set."""
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    with pytest.raises(EarningsProviderError, match="EODHD_API_KEY"):
        EodhdEarningsProvider()


def test_explicit_api_key_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key=`` argument is honored even when the env var is absent."""
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    p = EodhdEarningsProvider(api_key="explicit")
    assert p._api_key == "explicit"


# ── Smoke: total window with single day ──────────────────────────────────


def test_fetch_single_day(monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 1-day window issues exactly one HTTP call."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    session = _MockSession([_MockResponse(200, [])])
    p = EodhdEarningsProvider(session=session)
    p.fetch(["AAPL"], date(2024, 2, 15), date(2024, 2, 15))
    assert len(session.calls) == 1
    assert session.calls[0]["params"]["from"] == "2024-02-15"
    assert session.calls[0]["params"]["to"] == "2024-02-15"


# ── Tests: incremental_fetch ─────────────────────────────────────────────


def _aapl_row(report_date: str, **overrides: Any) -> dict[str, Any]:
    """Build a single AAPL earnings row with sensible defaults."""
    base = {
        "code": "AAPL.US",
        "report_date": report_date,
        "date": report_date,
        "before_after_market": "AfterMarket",
        "currency": "USD",
        "actual": 1.0,
        "estimate": 0.9,
        "difference": 0.1,
        "percent": 11.11,
    }
    base.update(overrides)
    return base


def test_incremental_fetch_no_cache_uses_one_year_backfill(
    monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch, tmp_optopsy_dir: Path
) -> None:
    """With no cache, ``incremental_fetch`` defaults to a 1-year window."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    today = date(2026, 1, 15)
    expected_start = today - timedelta(days=365)
    payload = {"type": "Earnings", "earnings": [_aapl_row("2025-12-15")]}
    # A 1-year window chunks into ~13 monthly HTTP calls.
    session = _MockSession([_MockResponse(200, payload) for _ in range(13)])
    p = EodhdEarningsProvider(session=session)
    p.incremental_fetch(["AAPL"], end_date=today, cache_root=tmp_optopsy_dir)
    # 13 monthly windows means 13 HTTP calls.
    assert len(session.calls) == 13
    # The first window's from should be the backfill start.
    # of it — month windows chunk to ~30 days, so we just sanity-check
    # it's not the empty default and not the end date).
    assert session.calls[0]["params"]["from"] == expected_start.isoformat()


def test_incremental_fetch_no_cache_window_override(
    monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch, tmp_optopsy_dir: Path
) -> None:
    """``no_cache_window_days`` overrides the default 1-year backfill window."""
    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    today = date(2026, 1, 15)
    expected_start = today - timedelta(days=730)
    payload = {"type": "Earnings", "earnings": [_aapl_row("2025-12-15")]}
    # 2 years chunks into ~25 monthly HTTP calls.
    session = _MockSession([_MockResponse(200, payload) for _ in range(25)])
    p = EodhdEarningsProvider(session=session)
    p.incremental_fetch(
        ["AAPL"],
        end_date=today,
        no_cache_window_days=730,
        cache_root=tmp_optopsy_dir,
    )
    assert len(session.calls) == 25
    assert session.calls[0]["params"]["from"] == expected_start.isoformat()


def test_incremental_fetch_uses_cache_latest_minus_overlap(
    monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch, tmp_optopsy_dir: Path
) -> None:
    """With a cache, ``incremental_fetch`` queries from latest - overlap_days."""
    # Seed the cache with one event on 2024-06-30.
    seed = EarningsCalendar(
        events=[
            EarningsEvent(
                code="AAPL.US",
                report_date=datetime(2024, 6, 30, tzinfo=UTC),
            )
        ]
    ).to_dataframe()
    write_earnings("AAPL.US", seed, root=tmp_optopsy_dir)

    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    # Vendor returns one new row.
    payload = {"type": "Earnings", "earnings": [_aapl_row("2024-09-30")]}
    # 2024-06-23 to 2024-12-31 = ~7 monthly windows.
    session = _MockSession([_MockResponse(200, payload) for _ in range(7)])
    p = EodhdEarningsProvider(session=session)
    p.incremental_fetch(
        ["AAPL"],
        end_date=date(2024, 12, 31),
        overlap_days=7,
        cache_root=tmp_optopsy_dir,
    )
    assert len(session.calls) == 7
    # With latest=2024-06-30 and overlap_days=7, the start is 2024-06-23.
    # The end of the *first* 30-day window is 2024-07-22 (not the user-facing
    # 12-31, because month windows chunk into 30-day slices).
    assert session.calls[0]["params"]["from"] == "2024-06-23"
    assert session.calls[0]["params"]["to"] == "2024-07-22"


def test_incremental_fetch_skips_symbols_past_end(
    monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch, tmp_optopsy_dir: Path
) -> None:
    """If the latest cached row is already after ``end_date``, no HTTP call is made."""
    # Seed the cache with a row AFTER the requested end_date.
    seed = EarningsCalendar(
        events=[
            EarningsEvent(
                code="AAPL.US",
                report_date=datetime(2026, 6, 1, tzinfo=UTC),
            )
        ]
    ).to_dataframe()
    write_earnings("AAPL.US", seed, root=tmp_optopsy_dir)

    session = _MockSession([])  # no scripted responses
    p = EodhdEarningsProvider(session=session)
    events = p.incremental_fetch(
        ["AAPL"],
        end_date=date(2026, 1, 1),
        overlap_days=7,
        cache_root=tmp_optopsy_dir,
    )
    assert events == []
    assert session.calls == []  # no HTTP call made


def test_incremental_fetch_handles_mixed_symbols(
    monkeypatch_api_key: None, monkeypatch: pytest.MonkeyPatch, tmp_optopsy_dir: Path
) -> None:
    """Some symbols have cache, some don't — both are handled correctly."""
    # Seed AAPL with one row.
    seed = EarningsCalendar(
        events=[
            EarningsEvent(
                code="AAPL.US",
                report_date=datetime(2024, 1, 15, tzinfo=UTC),
            )
        ]
    ).to_dataframe()
    write_earnings("AAPL.US", seed, root=tmp_optopsy_dir)
    # MSFT has no cache.

    monkeypatch.setattr(eodhd_mod, "_MIN_INTERVAL_SEC", 0.0)
    payload = {
        "type": "Earnings",
        "earnings": [
            _aapl_row("2024-04-15", code="AAPL.US"),
            _aapl_row("2024-04-20", code="MSFT.US", actual=3.0, estimate=2.9),
        ],
    }
    # AAPL: 2024-01-08 to 2024-06-30 = ~6 windows. MSFT: 2023-07-01 to 2024-06-30
    # = ~12 windows. Over-allocate to 25 to be safe.
    session = _MockSession([_MockResponse(200, payload) for _ in range(25)])
    p = EodhdEarningsProvider(session=session)
    events = p.incremental_fetch(
        ["AAPL", "MSFT"],
        end_date=date(2024, 6, 30),
        overlap_days=7,
        cache_root=tmp_optopsy_dir,
    )
    # Both AAPL and MSFT events should come back (callers filter/dedup).
    assert {e.code for e in events} == {"AAPL.US", "MSFT.US"}
    # Each symbol gets its own multi-window fetch (~7 + ~12 = 19).
    assert len(session.calls) == 19
    # The two symbols' first windows should start at different dates
    # (AAPL: latest cached 2024-01-15 - 7 overlap = 2024-01-08;
    # MSFT: no cache, so 1-year backfill from 2024-06-30 = 2023-07-01).
    from_dates = sorted({c["params"]["from"] for c in session.calls})
    assert "2024-01-08" in from_dates
    assert "2023-07-01" in from_dates


# ── Sanity: timedelta arithmetic used by month windows ──────────────────


def test_window_spacing() -> None:
    """The end of window N and the start of window N+1 are exactly 1 day apart."""
    start = date(2024, 1, 1)
    end = start + timedelta(days=30)
    windows = eodhd_mod._month_windows(start, end)
    for (_, e1), (s2, _) in pairwise(windows):
        assert (s2 - e1).days == 1
