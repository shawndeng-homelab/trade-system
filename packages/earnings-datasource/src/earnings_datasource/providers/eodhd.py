"""EODHD earnings calendar provider.

Talks to ``https://eodhd.com/api/calendar/earnings`` and normalizes the
response into :class:`EarningsEvent` records.

Response shape (Corporate Events Calendar & News API plan)
----------------------------------------------------------
The endpoint returns a wrapped object::

    {
      "type": "Earnings",
      "description": "...",
      "from": "YYYY-MM-DD",
      "to": "YYYY-MM-DD",
      "earnings": [
        {
          "code": "AAPL.US",
          "report_date": "2024-02-01",        # announcement date
          "date": "2023-12-31",               # fiscal-period end
          "before_after_market": "AfterMarket",
          "currency": "USD",
          "actual": 2.18,
          "estimate": 2.11,
          "difference": 0.07,
          "percent": 3.3175                   # surprise as percent (not fraction)
        },
        ...
      ]
    }

Each row is a single announcement (no eps/revenue split in this plan —
revenue data, if needed, comes from the separate ``calendar/trends``
endpoint).
"""

import logging
import os
import re
import time as _time
from collections.abc import Callable
from collections.abc import Sequence
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import ClassVar

import requests

from earnings_datasource.models import EarningsEvent
from earnings_datasource.models import EarningsProviderError
from earnings_datasource.providers.base import BaseEarningsProvider
from earnings_datasource.providers.store import latest_report_date


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
        *,
        on_window: Callable[[int, int, date, date], None] | None = None,
    ) -> list[EarningsEvent]:
        """Fetch earnings events for *symbols* in ``[start_date, end_date]``.

        We always query by date window (not by ``symbols=``) so we can paginate
        predictably across multi-year backtests; symbols are filtered client-side.

        Args:
            symbols: Tickers to fetch.
            start_date: Inclusive start of the announcement-date window.
            end_date: Inclusive end of the announcement-date window.
            on_window: Optional ``(idx, total, window_from, window_to) -> None``
                callback invoked before each HTTP call, intended for progress
                reporting. ``idx`` is 1-based, ``total`` is the total window count.
        """
        if start_date > end_date:
            msg = f"start_date ({start_date}) is after end_date ({end_date})"
            raise EarningsProviderError(msg)

        canonical = [self.normalize_symbol(s) for s in symbols]
        canonical_set = set(canonical)
        all_events: list[EarningsEvent] = []

        windows = _month_windows(start_date, end_date)
        total = len(windows)
        for idx, (window_from, window_to) in enumerate(windows, start=1):
            params = {
                "from": window_from.isoformat(),
                "to": window_to.isoformat(),
                "fmt": "json",
            }
            rows = self._fetch_window(params)
            for ev in _normalize_rows(rows):
                if ev.code in canonical_set:
                    all_events.append(ev)
            if on_window is not None:
                # Invoke the callback *after* the window completes so the
                # caller can advance a progress bar to ``idx`` (this window
                # is now done).
                on_window(idx, total, window_from, window_to)

        # Sort by report_date ascending (stable across calls).
        all_events.sort(key=lambda e: (e.code, e.report_date))
        return all_events

    def incremental_fetch(
        self,
        symbols: Sequence[str],
        *,
        end_date: date | None = None,
        overlap_days: int = 7,
        no_cache_window_days: int = 365,
        cache_root: Path | None = None,
        on_window: Callable[[int, int, date, date], None] | None = None,
    ) -> list[EarningsEvent]:
        """Fetch only the rows the local cache is missing.

        For each symbol, inspect the parquet cache via
        :func:`latest_report_date`; if there are cached rows, the
        effective ``start_date`` is ``latest - overlap_days`` (so late
        vendor updates within the overlap window are still picked up).
        Symbols with no cache row fall back to a ``no_cache_window_days``
        day backfill (1 year by default; the CLI bumps this to 730).

        Args:
            symbols: Tickers to refresh.
            end_date: Inclusive upper bound (defaults to today).
            overlap_days: Days of overlap with the existing cache, to
                catch late restatements / corrections.
            no_cache_window_days: Backfill window for symbols with no
                cache row. Defaults to 365.
            cache_root: Override the data root (for tests).
            on_window: Optional ``(idx, total, window_from, window_to) -> None``
                callback invoked before each HTTP call across all symbols.

        Returns:
            A flat list of normalized :class:`EarningsEvent` records
            fetched from the vendor (caller is responsible for merging
            into the cache).
        """
        if end_date is None:
            end_date = date.today()

        canonical = [self.normalize_symbol(s) for s in symbols]
        per_symbol_windows: list[tuple[str, date, date]] = []
        for code in canonical:
            latest = latest_report_date(code, root=cache_root)
            start = (
                end_date - timedelta(days=no_cache_window_days)
                if latest is None
                else latest - timedelta(days=overlap_days)
            )
            if start > end_date:
                # Cache is already past the requested end — nothing to do.
                continue
            per_symbol_windows.append((code, start, end_date))

        all_events: list[EarningsEvent] = []
        for code, start, end in per_symbol_windows:
            events = self.fetch([code], start, end, on_window=on_window)
            all_events.extend(events)
        all_events.sort(key=lambda e: (e.code, e.report_date))
        return all_events

    # ── HTTP layer ────────────────────────────────────────────────────────

    def _fetch_window(self, params: dict[str, str]) -> list[dict[str, Any]]:
        """Issue a throttled GET with retry on 429/5xx; return the ``earnings`` list."""
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
                return _extract_earnings_list(payload)

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


def _extract_earnings_list(payload: Any) -> list[dict[str, Any]]:
    """Pull the ``earnings`` list out of an EODHD response.

    The paid-plan response is a ``{"earnings": [...], "type": ..., ...}``
    dict. Some endpoints (or error responses) return a bare list or a
    plain error dict; we raise on the latter.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "earnings" in payload and isinstance(payload["earnings"], list):
            return payload["earnings"]
        if "error" in payload or "message" in payload:
            msg = f"EODHD returned an error payload: {payload}"
            raise EarningsProviderError(msg)
    msg = f"unexpected EODHD payload shape: list/dict-with-'earnings' expected, got {type(payload).__name__}"
    raise EarningsProviderError(msg)


def _normalize_rows(rows: list[dict[str, Any]]) -> list[EarningsEvent]:
    """Convert raw EODHD rows into :class:`EarningsEvent` records.

    Skips rows that lack both ``code`` and ``report_date``. Each row maps
    1-to-1 to one event (no eps/revenue collapse in this plan).
    """
    events: list[EarningsEvent] = []
    for row in rows:
        code = row.get("code")
        report_date = row.get("report_date")
        if not code or not report_date:
            continue
        # Map the vendor field names to our schema. The model_validator
        # in ``EarningsEvent`` does the heavy lifting (parsing the date
        # string, deriving session, computing surprise, etc.).
        payload = {
            "code": code,
            "report_date": report_date,
            "fiscal_period_end": row.get("date"),  # fiscal-period end
            "before_after_market": row.get("before_after_market"),
            "currency": row.get("currency"),
            "estimate_eps": _maybe_float(row.get("estimate")),
            "actual_eps": _maybe_float(row.get("actual")),
            "percent": _maybe_float(row.get("percent")),
        }
        events.append(EarningsEvent.model_validate(payload))
    return events


def _maybe_float(value: Any) -> float | None:
    """Coerce a vendor numeric to ``float``; ``None`` if missing/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
