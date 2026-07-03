"""PMCC (Poor Man's Covered Call) backtest strategy.

Long a deep-ITM LEAPS call (far expiry, ~0.8 delta) + short a near-term OTM call
(~0.3 delta). Each leg is submitted as a separate order and reconciled through
:class:`~trade_system_strategies.shared.legs.LegGroup`.

This is a scaffold: ``on_option_chain`` selects legs via
:mod:`~trade_system_strategies.pmcc.signals` and the multi-leg submit/reconcile flow
is stubbed for incremental implementation.
"""

from nautilus_trader.model.data import Bar
from nautilus_trader.trading.strategy import Strategy

from trade_system_strategies.pmcc.config import PMCCConfig


class PMCCStrategy(Strategy):
    """Backtest strategy for a Poor Man's Covered Call.

    Args:
        config: The PMCC strategy configuration.

    """

    def __init__(self, config: PMCCConfig) -> None:
        """Initialize the PMCC strategy with its config."""
        super().__init__(config)
        self._config: PMCCConfig = config

    def on_start(self) -> None:
        """Subscribe to the underlying and option chains on startup."""
        # TODO: subscribe to near-term and far-expiry option chains for the underlying.

    def on_bar(self, bar: Bar) -> None:
        """Entry/roll decisions on each underlying bar."""
        # TODO: drive PMCC entry and rolling from bar events.

    def on_order_filled(self, event) -> None:
        """Reconcile each leg fill into the active :class:`LegGroup`."""
        # TODO: map event.client_order_id -> LegGroup.apply_fill(...).
