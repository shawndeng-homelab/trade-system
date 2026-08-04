"""Tests for EodhdEarningsProvider.

HTTP calls are mocked via a custom ``MockSession`` that returns canned
JSON responses, so no real EODHD requests are issued during tests.
"""

import json
from datetime import date
from datetime import timedelta
from itertools import pairwise
from typing import Any

import pytest
import requests
from earnings_datasource import EodhdEarningsProvider
from earnings_datasource.models import EarningsProviderError
from earnings_datasource.providers import eodhd as eodhd_mod


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


# ── Tests: collapse ──────────────────────────────────────────────────────


def test_collapse_two_rows_into_one_event(monkeypatch_api_key: None) -> None:
    """EODHD's eps+revenue pair collapses into one EarningsEvent."""
    raw = [
        {
            "code": "AAPL.US",
            "type": "eps",
            "date": "2024-08-01",
            "report_date": "2024-08-01T21:00:00+00:00",
            "before_market_open": None,
            "after_market_close": True,
            "estimate": 1.0,
            "actual": 1.2,
            "currency": "USD",
            "period": "Q3",
            "fiscal_year": 2024,
            "fiscal_quarter": 3,
        },
        {
            "code": "AAPL.US",
            "type": "revenue",
            "date": "2024-08-01",
            "report_date": "2024-08-01T21:00:00+00:00",
            "before_market_open": None,
            "after_market_close": True,
            "estimate": 100.0,
            "actual": 120.5,
            "currency": "USD",
            "period": "Q3",
            "fiscal_year": 2024,
            "fiscal_quarter": 3,
        },
    ]
    events = eodhd_mod._collapse(raw)
    assert len(events) == 1
    ev = events[0]
    assert ev.code == "AAPL.US"
    assert ev.estimate_eps == 1.0
    assert ev.actual_eps == 1.2
    assert ev.eps_surprise == pytest.approx(0.2)
    assert ev.estimate_revenue == 100.0
    assert ev.actual_revenue == 120.5
    assert ev.revenue_surprise == pytest.approx(20.5)
    assert ev.fiscal_year == 2024
    assert ev.fiscal_quarter == 3
    assert ev.fiscal_period == "2024Q3"
    assert ev.after_market_close is True


def test_collapse_skips_incomplete_rows() -> None:
    """Rows missing both ``code`` and ``report_date`` are skipped."""
    raw = [
        {"code": "AAPL.US", "report_date": "2024-08-01T21:00:00+00:00", "type": "eps"},
        {"code": None, "report_date": "2024-08-01T21:00:00+00:00", "type": "eps"},
        {"code": "MSFT.US", "report_date": None, "type": "eps"},
    ]
    events = eodhd_mod._collapse(raw)
    assert len(events) == 1
    assert events[0].code == "AAPL.US"


# ── Tests: fetch ─────────────────────────────────────────────────────────


def test_fetch_collapses_eps_and_revenue(monkeypatch_api_key: None) -> None:
    """End-to-end: two-row response collapses to one event."""
    raw = [
        {
            "code": "AAPL.US",
            "type": "eps",
            "report_date": "2024-02-01T21:30:00+00:00",
            "estimate": 2.0,
            "actual": 2.4,
        },
        {
            "code": "AAPL.US",
            "type": "revenue",
            "report_date": "2024-02-01T21:30:00+00:00",
            "estimate": 100.0,
            "actual": 120.0,
        },
    ]
    session = _MockSession([_MockResponse(200, raw)])
    p = EodhdEarningsProvider(session=session)
    events = p.fetch(["AAPL"], date(2024, 2, 1), date(2024, 2, 28))
    assert len(events) == 1
    assert events[0].code == "AAPL.US"
    assert events[0].actual_eps == 2.4
    assert events[0].actual_revenue == 120.0


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


# ── Sanity: timedelta arithmetic used by month windows ──────────────────


def test_window_spacing() -> None:
    """The end of window N and the start of window N+1 are exactly 1 day apart."""
    start = date(2024, 1, 1)
    end = start + timedelta(days=30)
    windows = eodhd_mod._month_windows(start, end)
    for (_, e1), (s2, _) in pairwise(windows):
        assert (s2 - e1).days == 1
