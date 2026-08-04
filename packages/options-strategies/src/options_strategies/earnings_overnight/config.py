"""Earnings overnight strategy configuration.

Defines all parameters for running an earnings-overnight backtest via optopsy.

The strategy enters a single 2% OTM option (call or put, whichever has
higher OI × Volume — "follow smart money") on the trading day before
earnings, and exits the next day after the announcement.

Known limitations (also documented in ``strategy.py``):

- optopsy's data is EOD-only, so the "3:30 PM entry" is approximated by
  the **T-1 daily high** (the closest EOD proxy for the late-session
  price) and the "T open exit" is approximated by the **T EOD** snapshot.
- The 2% OTM target uses ``reference_price`` (default ``"high"``) to
  pick the strike; downstream P&L is computed by optopsy from the same
  EOD bid/ask snapshots.
"""

from datetime import date as date_cls
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator


class EarningsOvernightConfig(BaseModel):
    """Earnings-overnight strategy parameters.

    Attributes:
        symbol: Primary underlying ticker (e.g. "SPY"). Single-symbol
            workflow; multi-symbol is a future extension.
        capital: Total starting capital in dollars.
        quantity: Number of contracts per trade.
        multiplier: Contract multiplier (100 for standard equity options).
        max_positions: Maximum concurrent open positions per leg.
        start_date: Optional start date filter (YYYY-MM-DD).
        end_date: Optional end date filter (YYYY-MM-DD).
        otm_target_pct: Target OTM percentage (0.02 = 2% OTM).
        otm_tolerance_pct: ± strike tolerance band around the target.
        reference_price: Which T-1 OHLCV field anchors the strike.
            ``"high"`` is the closest EOD proxy for a 3:30 PM price.
        min_oi: Minimum open interest for a candidate to qualify.
        min_volume: Minimum volume for a candidate to qualify.
        max_entry_dte: DTE upper bound (forces "nearest expiry" semantics).
        min_entry_dte: DTE lower bound (allow 0DTE entries).
        cost_cap_usd: Maximum debit per position. Events whose top
            candidate exceeds this are skipped (no entry, no quantity
            rescaling).
        call_weight: Capital weight for the call leg.
        put_weight: Capital weight for the put leg.
        as_of_date: Optional backtest cutoff. Filters out earnings events
            that EODHD has pre-published into the future but that have
            not yet been announced at the time of the backtest. Always
            set this in production backtests to avoid peeking ahead.
    """

    model_config = ConfigDict(frozen=True)

    # ── General ────────────────────────────────────────────────────────────
    symbol: str = "SPY"
    capital: float = Field(100_000.0, gt=0)
    quantity: int = Field(1, gt=0)
    multiplier: int = Field(100, gt=0)
    max_positions: int = Field(1, gt=0)

    # ── Data window ────────────────────────────────────────────────────────
    start_date: str | None = None
    end_date: str | None = None
    as_of_date: date_cls | None = None

    # ── Strike selection ───────────────────────────────────────────────────
    otm_target_pct: float = Field(0.02, gt=0, lt=1)
    otm_tolerance_pct: float = Field(0.005, gt=0, lt=1)
    reference_price: Literal["high", "close"] = "high"

    # ── Liquidity filter ("follow smart money") ────────────────────────────
    min_oi: int = Field(100, ge=0)
    min_volume: int = Field(50, ge=0)

    # ── Expiration ─────────────────────────────────────────────────────────
    max_entry_dte: int = Field(14, gt=0)
    min_entry_dte: int = Field(0, ge=0)

    # ── Cost cap ───────────────────────────────────────────────────────────
    cost_cap_usd: float = Field(1000.0, gt=0)

    # ── Portfolio weights ──────────────────────────────────────────────────
    call_weight: float = Field(0.5, gt=0, le=1)
    put_weight: float = Field(0.5, gt=0, le=1)

    @model_validator(mode="after")
    def _check_cross_field(self) -> "EarningsOvernightConfig":
        """Validate cross-field invariants."""
        if self.min_entry_dte >= self.max_entry_dte:
            msg = f"min_entry_dte ({self.min_entry_dte}) must be < max_entry_dte ({self.max_entry_dte})"
            raise ValueError(msg)
        if abs(self.call_weight + self.put_weight - 1.0) > 1e-6:
            msg = f"call_weight ({self.call_weight}) + put_weight ({self.put_weight}) must sum to 1.0"
            raise ValueError(msg)
        if self.otm_tolerance_pct >= self.otm_target_pct:
            msg = f"otm_tolerance_pct ({self.otm_tolerance_pct}) must be < otm_target_pct ({self.otm_target_pct})"
            raise ValueError(msg)
        return self
