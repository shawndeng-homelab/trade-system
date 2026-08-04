"""EODHD earnings calendar provider.

Talks to ``https://eodhd.com/api/calendar/earnings`` and normalizes the
response into :class:`EarningsEvent` records.

Caveats specific to EODHD's calendar endpoint
---------------------------------------------
- One physical announcement yields two rows (one ``type="eps"``, one
  ``type="revenue"``). We collapse them on ``(code, report_date)``.
- The endpoint ignores ``from``/``to`` when ``symbols`` is supplied
  (it returns the next 4-12 weeks of forward calendar plus the trailing
  history). For multi-year backtests we therefore **don't pass** symbols
  and instead slice the calendar by date.
- We always paginate by 30-day windows to keep HTTP responses small and
  predictable (the API does not publish a hard limit, but a ~30-day
  window has been observed to be safe).
"""

import logging
import os
import re
import time as _time
from collections.abc import Sequence
from datetime import date
from datetime import timedelta
from typing import Any
from typing import ClassVar

import requests

from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from earnings_datasource.providers.base import BaseEarningsProvider


logger = logging.getLogger(__name__)


_BASE_URL = "https://eodhd.com/api/calendar/earnings"
_WINDOW_DAYS = 30
_MIN_INTERVAL_SEC = 0.1
_TIMEOUT_SEC = 30
_MAX_RETRIES = 5
_BACKOFF_FACTOR = 2.0

# Match a bare `api_token=...` value inside a URL or query string and
# replace it with `***`. Anchored to a query-param boundary so a stray
# `backup_api_token=` or path segment is left alone.
_TOKEN_RE = re.compile(r"([?&]api_token=)[^&#]*")


def _redact_token(url: str) -> str:
    """Redact the ``api_token`` query value from a URL string."""
    return _TOKEN_RE.sub(r"\1***", url)


class EodhdEarningsProvider(BaseEarningsProvider):
    """EODHD earnings-calendar provider.

    Auth via the ``EODHD_API_KEY`` env var (or pass ``api_key=`` explicitly).
    """

    source_name: ClassVar[str] = "eodhd"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: EODHD API token. Falls back to ``EODHD_API_KEY`` env var.
            session: Optional pre-configured ``requests.Session`` (for testing).
        """
        self._api_key = api_key or os.environ.get("EODHD_API_KEY")
        if not self._api_key:
            msg = (
                "EODHD_API_KEY is not set. Pass api_key= or export the env var "
                "before instantiating EodhdEarningsProvider."
            )
            raise EarningsProviderError(msg)
        self._session = session or requests.Session()
        self._last_request_monotonic = 0.0

    # ── BaseEarningsProvider interface ────────────────────────────────────

    def normalize_symbol(self, symbol: str) -> str:
        """Append ``.US`` to bare tickers; pass through ``AAPL.US``/``BMW.XETRA``."""
        s = symbol.strip().upper()
        if "." in s:
            return s
        return f"{s}.US"

    def cache_key(self, symbol: str) -> str:
        """Cache filename stem (matches the vendor-native identifier)."""
        return self.normalize_symbol(symbol)

    def fetch(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> list[EarningsEvent]:
        """Fetch earnings events for *symbols* in ``[start_date, end_date]``.

        We always query by date window (not by ``symbols=``) so we can paginate
        predictably across multi-year backtests; symbols are filtered client-side.
        """
        if start_date > end_date:
            msg = f"start_date ({start_date}) is after end_date ({end_date})"
            raise EarningsProviderError(msg)

        canonical = [self.normalize_symbol(s) for s in symbols]
        canonical_set = set(canonical)
        all_events: list[EarningsEvent] = []

        for window_from, window_to in _month_windows(start_date, end_date):
            params = {
                "from": window_from.isoformat(),
                "to": window_to.isoformat(),
                "fmt": "json",
            }
            rows = self._fetch_window(params)
            for ev in _collapse(rows):
                if ev.code in canonical_set:
                    all_events.append(ev)

        # Sort by report_date ascending (stable across calls).
        all_events.sort(key=lambda e: (e.code, e.report_date))
        return all_events

    # ── HTTP layer ────────────────────────────────────────────────────────

    def _fetch_window(self, params: dict[str, str]) -> list[dict[str, Any]]:
        """Issue a throttled GET with retry on 429/5xx; return the JSON list."""
        url = _BASE_URL
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            self._throttle()
            request_params = {**params, "api_token": self._api_key, "fmt": "json"}
            try:
                resp = self._session.get(url, params=request_params, timeout=_TIMEOUT_SEC)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "EODHD request failed (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )
                self._sleep_backoff(attempt)
                continue

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                except ValueError as exc:
                    last_exc = exc
                    logger.warning("EODHD returned non-JSON: %s", exc)
                    self._sleep_backoff(attempt)
                    continue
                if not isinstance(payload, list):
                    msg = f"unexpected EODHD payload shape: list expected, got {type(payload).__name__}"
                    raise EarningsProviderError(msg)
                return payload

            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = EarningsProviderError(f"EODHD HTTP {resp.status_code}: {resp.reason}")
                logger.warning(
                    "EODHD transient error %d (attempt %d/%d)",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                self._sleep_backoff(attempt)
                continue

            # Non-retryable: log with redacted URL and raise.
            redacted = _redact_token(resp.url or url)
            msg = f"EODHD HTTP {resp.status_code} for {redacted}: {resp.text[:200]}"
            raise EarningsProviderError(msg)

        msg = f"EODHD gave up after {_MAX_RETRIES} attempts: {last_exc}"
        raise EarningsProviderError(msg)

    def _throttle(self) -> None:
        """Enforce a minimum interval between HTTP requests."""
        now = _time.monotonic()
        elapsed = now - self._last_request_monotonic
        if elapsed < _MIN_INTERVAL_SEC:
            _time.sleep(_MIN_INTERVAL_SEC - elapsed)
        self._last_request_monotonic = _time.monotonic()

    def _sleep_backoff(self, attempt: int) -> None:
        """Sleep with exponential backoff before a retry."""
        _time.sleep(_BACKOFF_FACTOR**attempt)


# ── Helpers ───────────────────────────────────────────────────────────────


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into a list of <=30-day inclusive windows.

    The final window may be shorter than 30 days so the upper bound lands
    exactly on ``end``.
    """
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=_WINDOW_DAYS - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _collapse(raw_rows: list[dict[str, Any]]) -> list[EarningsEvent]:
    """Collapse EODHD's two-row-per-announcement layout into one event each.

    EODHD returns one row per ``(code, report_date, type)`` where ``type``
    is ``"eps"`` or ``"revenue"``. The shared fields
    (``code``, ``date``, ``report_date``, ``before_market_open``,
    ``after_market_close``, ``currency``, ``period``, ``fiscal_year``,
    ``fiscal_quarter``) are merged; the per-type fields (``estimate``,
    ``actual``) populate the matching ``*_eps`` or ``*_revenue`` slots.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw_rows:
        code = row.get("code")
        report_date = row.get("report_date") or row.get("date")
        if not code or not report_date:
            # Skip rows that don't have enough to identify the announcement.
            continue
        key = (code, report_date)
        bucket = grouped.setdefault(key, {})
        # Shared fields — only set if not already present (rows are
        # not guaranteed to be ordered).
        for shared in (
            "code",
            "date",
            "report_date",
            "before_market_open",
            "after_market_close",
            "currency",
            "period",
            "fiscal_year",
            "fiscal_quarter",
        ):
            if shared in row and shared not in bucket:
                bucket[shared] = row[shared]
        # Per-type fields.
        row_type = row.get("type")
        if row_type == "eps":
            bucket["estimate_eps"] = _maybe_float(row.get("estimate"))
            bucket["actual_eps"] = _maybe_float(row.get("actual"))
        elif row_type == "revenue":
            bucket["estimate_revenue"] = _maybe_float(row.get("estimate"))
            bucket["actual_revenue"] = _maybe_float(row.get("actual"))

    events: list[EarningsEvent] = []
    for bucket in grouped.values():
        # ``report_date`` is the wire time; ``date`` (if distinct) is the
        # announcement calendar date. We prefer ``report_date`` for tz-aware
        # precision; if only ``date`` is present, use it.
        if "report_date" in bucket:
            bucket["report_date"] = bucket["report_date"]
        elif "date" in bucket:
            bucket["report_date"] = bucket["date"]
        events.append(EarningsEvent.model_validate(bucket))
    return events


def _maybe_float(value: Any) -> float | None:
    """Coerce a vendor numeric to ``float``; ``None`` if missing/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
