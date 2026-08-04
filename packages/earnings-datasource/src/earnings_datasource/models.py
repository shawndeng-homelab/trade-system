"""Pydantic models for the earnings-calendar data source.

A unified, vendor-agnostic schema for earnings announcements. Vendors
(EODHD today; Unusual Whales, SEC EDGAR, etc. later) normalize their
raw responses into a list of :class:`EarningsEvent` objects.

Conventions
-----------
- ``report_date`` is a tz-aware ``datetime`` at UTC midnight; the
  EODHD feed only gives a calendar date (no wire timestamp), so
  ``session`` is a coarse BMO/AMC/unknown label carried from the vendor.
- The vendor-native identifier (``code`` like ``"AAPL.US"``) is preserved
  alongside the bare ticker (``symbol`` like ``"AAPL"``) so consumers
  can join on either.
- All monetary fields are nullable: small-cap names and non-US issuers
  frequently omit estimates or actuals.
- ``eps_surprise`` is ``actual_eps - estimate_eps``; ``eps_surprise_pct``
  is the surprise as a decimal fraction (``0.05 = 5%``).
"""

import contextlib
from datetime import UTC
from datetime import date as date_cls
from datetime import datetime
from typing import Any
from typing import Literal

import pandas as pd
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import model_validator


Session = Literal["bmo", "amc", "unknown"]
Source = Literal["eodhd"]


class EarningsProviderError(Exception):
    """Raised when a provider fails to fetch or normalize earnings data."""


class EarningsEvent(BaseModel):
    """A single earnings announcement, normalized from any vendor.

    Attributes:
        code: Vendor-native identifier with exchange suffix (e.g. ``AAPL.US``).
        symbol: Bare ticker (e.g. ``AAPL``). Derived from ``code`` if absent.
        report_date: Tz-aware UTC datetime at midnight (the announcement date).
        fiscal_period_end: Fiscal-period end date reported by the vendor
            (e.g. ``2023-12-31`` for Q4 2023). ``None`` if not provided.
        session: Coarse timing label: ``bmo`` (before market open),
            ``amc`` (after market close), or ``unknown`` if vendor is silent.
        estimate_eps: Pre-announcement consensus EPS estimate.
        actual_eps: Reported EPS.
        eps_surprise: ``actual_eps - estimate_eps``; ``None`` if either is missing.
        eps_surprise_pct: Surprise as a decimal fraction (``0.05 = 5%``).
        currency: Reporting currency code (e.g. ``USD``).
        source: Provenance tag.
    """

    model_config = ConfigDict(frozen=True)

    # ── Identity ───────────────────────────────────────────────────────────
    code: str
    symbol: str

    # ── When ───────────────────────────────────────────────────────────────
    report_date: datetime
    fiscal_period_end: date_cls | None = None
    session: Session = "unknown"

    # ── Estimates vs actuals ───────────────────────────────────────────────
    estimate_eps: float | None = None
    actual_eps: float | None = None
    eps_surprise: float | None = None
    eps_surprise_pct: float | None = None
    currency: str | None = None

    # ── Provenance ─────────────────────────────────────────────────────────
    source: Source = "eodhd"

    @model_validator(mode="before")
    @classmethod
    def _derive_fields(cls, data: Any) -> Any:
        """Derive ``symbol``, normalize ``report_date``, compute surprises."""
        if not isinstance(data, dict):
            return data

        # Derive symbol from code (EODHD: "AAPL.US" -> "AAPL").
        if "code" in data and "symbol" not in data:
            data["symbol"] = str(data["code"]).split(".", 1)[0]

        # Normalize report_date to a tz-aware datetime.
        rd = data.get("report_date")
        if isinstance(rd, str):
            data["report_date"] = _parse_date(rd)
        elif isinstance(rd, datetime) and rd.tzinfo is None:
            data["report_date"] = rd.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)

        # Normalize fiscal_period_end.
        fpe = data.get("fiscal_period_end")
        if isinstance(fpe, str):
            try:
                data["fiscal_period_end"] = date_cls.fromisoformat(fpe)
            except ValueError:
                data["fiscal_period_end"] = None

        # Derive session from before_after_market label.
        bam = data.get("before_after_market") or data.get("session")
        if isinstance(bam, str):
            normalized = bam.strip().lower().replace(" ", "")
            if normalized in {"beforemarket", "bmo", "premarket"}:
                data["session"] = "bmo"
            elif normalized in {"aftermarket", "amc", "postmarket"}:
                data["session"] = "amc"
            else:
                data["session"] = "unknown"

        # Recompute eps_surprise from actual - estimate (EODHD provides
        # these but we re-derive to be safe across vendors).
        data["eps_surprise"] = _safe_subtract(data.get("actual_eps"), data.get("estimate_eps"))

        # Map EODHD's "percent" field (e.g. 3.3175) to a decimal fraction
        # (0.033175). EODHD sends percent as already-percent; we normalize
        # to fraction so consumers can multiply by 100 for display.
        # ``eps_surprise_pct`` is only meaningful when both estimate and
        # actual are present; otherwise drop it.
        has_both_sides = data.get("actual_eps") is not None and data.get("estimate_eps") is not None
        if has_both_sides:
            pct = data.get("eps_surprise_pct")
            if pct is None and "percent" in data and data["percent"] is not None:
                with contextlib.suppress(TypeError, ValueError):
                    data["eps_surprise_pct"] = float(data["percent"]) / 100.0
            elif pct is not None:
                # Caller passed eps_surprise_pct directly; assume already a fraction.
                data["eps_surprise_pct"] = float(pct)
        else:
            data["eps_surprise_pct"] = None

        return data


def _parse_date(s: str) -> datetime:
    """Parse a YYYY-MM-DD string into a tz-aware UTC midnight datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "T" in s:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    # Pure date.
    d = date_cls.fromisoformat(s)
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _safe_subtract(actual: float | None, estimate: float | None) -> float | None:
    """Subtract, returning ``None`` if either operand is missing."""
    if actual is None or estimate is None:
        return None
    return float(actual) - float(estimate)


class EarningsCalendar(BaseModel):
    """A bundle of earnings events with a canonical DataFrame projection.

    Attributes:
        events: List of :class:`EarningsEvent`.
        source: Provenance tag applied to all events.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    events: list[EarningsEvent]
    source: Source = "eodhd"

    def to_dataframe(self) -> pd.DataFrame:
        """Return a canonical DataFrame with one row per announcement.

        Columns (in order):
            ``code``, ``symbol``, ``report_date``, ``report_date_utc``,
            ``fiscal_period_end``, ``session``,
            ``estimate_eps``, ``actual_eps``, ``eps_surprise``,
            ``eps_surprise_pct``, ``currency``, ``source``.

        ``report_date`` is a tz-naive ``datetime`` at UTC midnight (the
        canonical join key for optopsy's signal filter). ``report_date_utc``
        is the same value as a tz-aware datetime.
        """
        if not self.events:
            return _empty_calendar_df()

        rows = []
        for ev in self.events:
            rd_utc = ev.report_date
            midnight_naive = rd_utc.replace(tzinfo=None) if rd_utc.tzinfo else rd_utc
            rows.append(
                {
                    "code": ev.code,
                    "symbol": ev.symbol,
                    "report_date": midnight_naive,
                    "report_date_utc": rd_utc,
                    "fiscal_period_end": ev.fiscal_period_end,
                    "session": ev.session,
                    "estimate_eps": ev.estimate_eps,
                    "actual_eps": ev.actual_eps,
                    "eps_surprise": ev.eps_surprise,
                    "eps_surprise_pct": ev.eps_surprise_pct,
                    "currency": ev.currency,
                    "source": ev.source,
                }
            )
        return pd.DataFrame.from_records(rows)


def _empty_calendar_df() -> pd.DataFrame:
    """Empty DataFrame with the canonical column order."""
    return pd.DataFrame(
        columns=[
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
    )
