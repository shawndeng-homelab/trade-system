"""Iron Condor strategy configuration.

Defines all parameters for running an iron condor backtest via optopsy.
An iron condor consists of four legs: long put (wing), short put (income),
short call (income), long call (wing).  This is a neutral income strategy
that profits when the underlying stays between the two short strikes.

Supports multiple entry cycles via ``entry_cycle``:

- ``"daily"`` — enter every trading day (0DTE / near-expiry style)
- ``"weekly"`` — enter once per week (standard weekly iron condor)
- ``"biweekly"`` — enter once every two weeks (two-week iron condor)
- ``"monthly"`` — enter once per month

With EODHD daily-frequency data, many expiration-day (DTE=0) rows are
missing, so ``exit_dte_tolerance`` is recommended to allow flexible exit
matching.
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class OdteIronCondorConfig(BaseModel):
    """Iron condor strategy parameters backed by optopsy.

    Attributes:
        symbol: Primary underlying ticker (e.g. "SPY").
        capital: Total starting capital in dollars.
        quantity: Number of contracts per trade.
        multiplier: Contract multiplier (100 for standard equity options).
        max_positions: Maximum concurrent open positions per leg.
        start_date: Optional start date filter (YYYY-MM-DD).
        end_date: Optional end date filter (YYYY-MM-DD).
        symbols: List of underlying tickers to trade (e.g. ["SPY", "QQQ", "IWM"]).
        entry_cycle: How often to open new positions.  One of "daily",
            "weekly", "biweekly", "monthly".  Controls the entry-date
            signal frequency (see ``signals.py``).
        long_put_delta: Target delta for long put wing (default 0.10).
        long_put_delta_min: Min delta for long put selection.
        long_put_delta_max: Max delta for long put selection.
        short_put_delta: Target delta for short put income leg (default 0.30).
        short_put_delta_min: Min delta for short put selection.
        short_put_delta_max: Max delta for short put selection.
        short_call_delta: Target delta for short call income leg (default 0.30).
        short_call_delta_min: Min delta for short call selection.
        short_call_delta_max: Max delta for short call selection.
        long_call_delta: Target delta for long call wing (default 0.10).
        long_call_delta_min: Min delta for long call selection.
        long_call_delta_max: Max delta for long call selection.
        max_entry_dte: Max DTE for entry (default 3 for near-expiry,
            use 14 for biweekly, 30 for monthly).
        exit_dte: Exit DTE (0 = expire same day, 7 = exit one week before expiry).
        exit_dte_tolerance: Tolerance for exit DTE matching (default 1).
            With EODHD data many DTE=0 rows are missing; tolerance=1 allows
            exit at DTE 0 or 1 so more trades complete successfully.
        take_profit: Take-profit threshold (0.5 = 50% of credit received).
        stop_loss: Stop-loss threshold (negative, e.g. -2.0 = lose 2x credit).
        entry_time: Target entry time HH:MM (e.g. "15:30" for 30 min before close).
            Note: intraday filtering requires intraday data; with daily data
            this is informational only and every trading day is an entry day.
    """

    model_config = ConfigDict(frozen=True)

    # ── General ────────────────────────────────────────────────────────────
    symbol: str = "SPY"
    capital: float = 100_000.0
    quantity: int = Field(1, gt=0)
    multiplier: int = Field(100, gt=0)
    max_positions: int = Field(1, gt=0)

    # ── Data ───────────────────────────────────────────────────────────────
    start_date: str | None = None
    end_date: str | None = None
    symbols: list[str] = Field(["SPY"], min_length=1)

    # ── Entry cycle ────────────────────────────────────────────────────────
    entry_cycle: str = Field("daily", pattern="^(daily|weekly|biweekly|monthly)$")

    # ── Long put wing (leg 1) ──────────────────────────────────────────────
    long_put_delta: float = Field(0.10, gt=0, le=1)
    long_put_delta_min: float = Field(0.05, gt=0, le=1)
    long_put_delta_max: float = Field(0.15, gt=0, le=1)

    # ── Short put income (leg 2) ───────────────────────────────────────────
    short_put_delta: float = Field(0.30, gt=0, le=1)
    short_put_delta_min: float = Field(0.25, gt=0, le=1)
    short_put_delta_max: float = Field(0.35, gt=0, le=1)

    # ── Short call income (leg 3) ──────────────────────────────────────────
    short_call_delta: float = Field(0.30, gt=0, le=1)
    short_call_delta_min: float = Field(0.25, gt=0, le=1)
    short_call_delta_max: float = Field(0.35, gt=0, le=1)

    # ── Long call wing (leg 4) ─────────────────────────────────────────────
    long_call_delta: float = Field(0.10, gt=0, le=1)
    long_call_delta_min: float = Field(0.05, gt=0, le=1)
    long_call_delta_max: float = Field(0.15, gt=0, le=1)

    # ── DTE ────────────────────────────────────────────────────────────────
    max_entry_dte: int = Field(3, gt=0)
    exit_dte: int = Field(0, ge=0)
    exit_dte_tolerance: int = Field(1, ge=0)

    # ── Risk management ────────────────────────────────────────────────────
    take_profit: float = Field(0.5, gt=0)
    stop_loss: float = Field(-2.0, lt=0)

    # ── Entry timing ───────────────────────────────────────────────────────
    entry_time: str = "15:30"
