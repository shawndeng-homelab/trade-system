"""PMCC (Poor Man's Covered Call) strategy configuration.

Defines all parameters for running a PMCC backtest via optopsy.
Two independent legs: long LEAPS (deep-ITM, far expiry) + short near-term OTM call.
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class PmccConfig(BaseModel):
    """PMCC strategy parameters backed by optopsy.

    Attributes:
        symbol: Underlying ticker (e.g. "SPY").
        capital: Total starting capital in dollars.
        quantity: Number of contracts per trade.
        multiplier: Contract multiplier (100 for standard equity options).
        max_positions: Maximum concurrent open positions per leg.
        start_date: Optional start date filter (YYYY-MM-DD).
        end_date: Optional end date filter (YYYY-MM-DD).
        expiration_type: "monthly" or "weekly".
        leaps_delta: Target delta for LEAPS leg (default 0.80).
        leaps_delta_min: Min delta for LEAPS selection.
        leaps_delta_max: Max delta for LEAPS selection.
        leaps_max_entry_dte: Max DTE for LEAPS entry (far month).
        leaps_exit_dte: Exit DTE for LEAPS (must be < leaps_max_entry_dte).
        leaps_max_hold_days: Optional max hold days for LEAPS.
        short_delta: Target delta for short call leg (default 0.30).
        short_delta_min: Min delta for short call selection.
        short_delta_max: Max delta for short call selection.
        short_max_entry_dte: Max DTE for short call entry (near term).
        short_exit_dte: Exit DTE for short call.
        short_take_profit: Take-profit threshold for short call (0.8 = 80% profit).
        short_stop_loss: Stop-loss threshold for short call (negative, e.g. -2.0 = lose 2× premium).
        short_max_hold_days: Optional max hold days for short call.
        leaps_weight: Capital allocation weight for LEAPS leg.
        short_weight: Capital allocation weight for short call leg.
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
    expiration_type: str = "monthly"

    # ── LEAPS leg ──────────────────────────────────────────────────────────
    leaps_delta: float = Field(0.80, gt=0, le=1)
    leaps_delta_min: float = Field(0.75, gt=0, le=1)
    leaps_delta_max: float = Field(0.85, gt=0, le=1)
    leaps_max_entry_dte: int = Field(365, gt=0)
    leaps_exit_dte: int = Field(30, ge=0)
    leaps_max_hold_days: int | None = None

    # ── Short call leg ─────────────────────────────────────────────────────
    short_delta: float = Field(0.30, gt=0, le=1)
    short_delta_min: float = Field(0.25, gt=0, le=1)
    short_delta_max: float = Field(0.35, gt=0, le=1)
    short_max_entry_dte: int = Field(45, gt=0)
    short_exit_dte: int = Field(7, ge=0)
    short_take_profit: float = Field(0.8, gt=0)
    short_stop_loss: float | None = Field(None, lt=0)
    short_max_hold_days: int | None = None

    # ── Portfolio weights ──────────────────────────────────────────────────
    leaps_weight: float = Field(0.6, gt=0, le=1)
    short_weight: float = Field(0.4, gt=0, le=1)
