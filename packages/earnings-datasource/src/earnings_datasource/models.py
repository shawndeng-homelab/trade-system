"""Pydantic models for the earnings-calendar data source.

A unified, vendor-agnostic schema for earnings announcements. Vendors
(EODHD today; Unusual Whales, SEC EDGAR, etc. later) normalize their
raw responses into a list of :class:`EarningsEvent` objects.

Conventions
-----------
- ``report_date`` is a tz-aware ``datetime`` (UTC) so BMO/AMC timing is
  preserved. The ``session`` field carries the BMO/AMC/intraday label
  derived from US/Eastern clock time.
- The vendor-native identifier (``code`` like ``"AAPL.US"``) is preserved
  alongside the bare ticker (``symbol`` like ``"AAPL"``) so consumers
  can join on either.
- All monetary fields are nullable: small-cap names and non-US issuers
  frequently omit estimates or actuals.
"""

from datetime import UTC
from datetime import datetime
from datetime import time
from typing import Any
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import model_validator


NYSE = ZoneInfo("America/New_York")
_BMO_CUTOFF = time(9, 30)
_AMC_CUTOFF = time(16, 0)

Session = Literal["bmo", "amc", "intraday", "unknown"]
Source = Literal["eodhd"]


class EarningsProviderError(Exception):
    """Raised when a provider fails to fetch or normalize earnings data."""


class EarningsEvent(BaseModel):
    """A single earnings announcement, normalized from any vendor.

    Attributes:
        code: Vendor-native identifier with exchange suffix (e.g. ``AAPL.US``).
        symbol: Bare ticker (e.g. ``AAPL``). Derived from ``code`` if absent.
        report_date: Tz-aware UTC datetime of the wire time (EODHD: sub-second precision).
        fiscal_year: Fiscal year of the reporting period.
        fiscal_quarter: Fiscal quarter (1..4) of the reporting period.
        fiscal_period: Canonical ``"YYYYQN"`` string, ``None`` if year/quarter unknown.
        session: BMO/AMC/intraday/unknown, derived from ``report_date`` in US/Eastern.
        before_market_open: Vendor-provided flag (US names only; ``None`` otherwise).
        after_market_close: Vendor-provided flag (US names only; ``None`` otherwise).
        estimate_eps: Pre-announcement consensus EPS estimate.
        actual_eps: Reported EPS.
        eps_surprise: ``actual_eps - estimate_eps``; ``None`` if either side missing.
        estimate_revenue: Pre-announcement consensus revenue estimate.
        actual_revenue: Reported revenue.
        revenue_surprise: ``actual_revenue - estimate_revenue``; ``None`` if either side missing.
        currency: Reporting currency code (e.g. ``USD``).
        period: Vendor label (e.g. ``Q1``, ``FY``, ``TTM``).
        source: Provenance tag.
    """

    model_config = ConfigDict(frozen=True)

    # ── Identity ───────────────────────────────────────────────────────────
    code: str
    symbol: str

    # ── When ───────────────────────────────────────────────────────────────
    report_date: datetime
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    fiscal_period: str | None = None
    session: Session = "unknown"
    before_market_open: bool | None = None
    after_market_close: bool | None = None

    # ── Estimates vs actuals ───────────────────────────────────────────────
    estimate_eps: float | None = None
    actual_eps: float | None = None
    eps_surprise: float | None = None
    estimate_revenue: float | None = None
    actual_revenue: float | None = None
    revenue_surprise: float | None = None
    currency: str | None = None
    period: str | None = None

    # ── Provenance ─────────────────────────────────────────────────────────
    source: Source = "eodhd"

    @model_validator(mode="before")
    @classmethod
    def _derive_fields(cls, data: Any) -> Any:
        """Derive ``symbol``, ``session``, ``fiscal_period`` and surprise fields."""
        if not isinstance(data, dict):
            return data

        # Derive symbol from code (EODHD: "AAPL.US" -> "AAPL").
        if "code" in data and "symbol" not in data:
            data["symbol"] = str(data["code"]).split(".", 1)[0]

        # Derive fiscal_period from year + quarter.
        if "fiscal_period" not in data and data.get("fiscal_year") and data.get("fiscal_quarter"):
            data["fiscal_period"] = f"{int(data['fiscal_year'])}Q{int(data['fiscal_quarter'])}"

        # Parse report_date if it's a string.
        rd = data.get("report_date")
        if isinstance(rd, str):
            data["report_date"] = _parse_iso(rd)
        if isinstance(rd, datetime) and rd.tzinfo is None:
            data["report_date"] = rd.replace(tzinfo=UTC)

        # Derive session from report_date in US/Eastern.
        rd_parsed = data.get("report_date")
        if isinstance(rd_parsed, datetime) and rd_parsed.tzinfo is not None:
            local = rd_parsed.astimezone(NYSE).time()
            if local < _BMO_CUTOFF:
                data["session"] = "bmo"
            elif local >= _AMC_CUTOFF:
                data["session"] = "amc"
            else:
                data["session"] = "intraday"

        # Compute surprises.
        data["eps_surprise"] = _safe_subtract(data.get("actual_eps"), data.get("estimate_eps"))
        data["revenue_surprise"] = _safe_subtract(data.get("actual_revenue"), data.get("estimate_revenue"))

        return data


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware datetime.

    Tolerates ``Z`` suffix (Python <3.11) and a missing timezone (assumes UTC).
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


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
            ``fiscal_year``, ``fiscal_quarter``, ``fiscal_period``,
            ``session``, ``before_market_open``, ``after_market_close``,
            ``estimate_eps``, ``actual_eps``, ``eps_surprise``,
            ``estimate_revenue``, ``actual_revenue``, ``revenue_surprise``,
            ``currency``, ``period``, ``source``.

        ``report_date`` is a tz-naive ``datetime`` at UTC midnight (the
        canonical join key for optopsy's signal filter). ``report_date_utc``
        is the full tz-aware datetime of the wire time.
        """
        if not self.events:
            return _empty_calendar_df()

        rows = []
        for ev in self.events:
            utc = ev.report_date
            midnight_utc = utc.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            rows.append(
                {
                    "code": ev.code,
                    "symbol": ev.symbol,
                    "report_date": midnight_utc,
                    "report_date_utc": utc,
                    "fiscal_year": ev.fiscal_year,
                    "fiscal_quarter": ev.fiscal_quarter,
                    "fiscal_period": ev.fiscal_period,
                    "session": ev.session,
                    "before_market_open": ev.before_market_open,
                    "after_market_close": ev.after_market_close,
                    "estimate_eps": ev.estimate_eps,
                    "actual_eps": ev.actual_eps,
                    "eps_surprise": ev.eps_surprise,
                    "estimate_revenue": ev.estimate_revenue,
                    "actual_revenue": ev.actual_revenue,
                    "revenue_surprise": ev.revenue_surprise,
                    "currency": ev.currency,
                    "period": ev.period,
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
    )
