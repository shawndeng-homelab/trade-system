"""Pre-defined metric instrument names and helpers for trade-system observability."""

from __future__ import annotations


# ── Counters ────────────────────────────────────────────────────────────

BARS_PROCESSED = "trade_system.bars.processed"
"""Number of bars processed by strategy."""

FILLS_COUNT = "trade_system.fills.count"
"""Number of fill events received."""

ORDERS_SUBMITTED = "trade_system.orders.submitted"
"""Number of orders submitted."""

POSITIONS_OPENED = "trade_system.positions.opened"
"""Number of positions opened."""

POSITIONS_CLOSED = "trade_system.positions.closed"
"""Number of positions closed."""

# ── Histograms ──────────────────────────────────────────────────────────

FILL_PNL = "trade_system.fill.pnl"
"""PnL of individual fills (realised)."""

POSITION_DURATION_SECS = "trade_system.position.duration_secs"
"""Duration of closed positions in seconds."""

# ── Gauges (observable) ────────────────────────────────────────────────

EQUITY = "trade_system.account.equity"
"""Current account equity."""

POSITION_COUNT = "trade_system.position.count"
"""Number of open positions."""
