"""Benchmark strategy configuration.

Defines parameters for a rolling ATM call benchmark: buy ATM call, hold until
DTE drops to ``exit_dte``, then close and immediately buy the next ATM call.
Repeats until the backtest end date.
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class BenchmarkConfig(BaseModel):
    """Rolling ATM call benchmark parameters backed by optopsy.

    The benchmark buys an ATM (delta ≈ 0.50) call and holds it until DTE
    drops to ``exit_dte`` (default 150).  At that point the position is
    closed and a new ATM call is immediately purchased on the next trading
    day.  This rolling behavior is achieved by providing every trading day
    as ``entry_dates`` combined with ``max_positions=1``: optopsy enters
    on the first available date, exits when DTE hits ``exit_dte``, and
    re-enters on the next trading day automatically.

    Attributes:
        symbols: List of underlying tickers to benchmark (e.g. ["SPY", "QQQ", "IWM"]).
        capital: Total starting capital in dollars.
        quantity: Number of contracts per trade.
        multiplier: Contract multiplier (100 for standard equity options).
        max_positions: Maximum concurrent open positions per leg (must be 1 for rolling).
        start_date: Optional start date filter (YYYY-MM-DD).
        end_date: Optional end date filter (YYYY-MM-DD).
        delta_target: Target delta for ATM call selection (default 0.50).
        delta_min: Min delta for ATM call selection.
        delta_max: Max delta for ATM call selection.
        max_entry_dte: Max DTE for entry (must be > exit_dte; default 730 for LEAPS).
        exit_dte: Exit when DTE drops to this value (default 150).
    """

    model_config = ConfigDict(frozen=True)

    # ── General ────────────────────────────────────────────────────────────
    symbols: list[str] = Field(["SPY", "QQQ", "IWM"], min_length=1)
    capital: float = 100_000.0
    quantity: int = Field(1, gt=0)
    multiplier: int = Field(100, gt=0)
    max_positions: int = Field(1, gt=0)

    # ── Data ───────────────────────────────────────────────────────────────
    start_date: str | None = None
    end_date: str | None = None

    # ── Delta targeting ────────────────────────────────────────────────────
    delta_target: float = Field(0.50, gt=0, le=1)
    delta_min: float = Field(0.45, gt=0, le=1)
    delta_max: float = Field(0.55, gt=0, le=1)

    # ── DTE ────────────────────────────────────────────────────────────────
    max_entry_dte: int = Field(730, gt=0)
    exit_dte: int = Field(150, ge=0)
