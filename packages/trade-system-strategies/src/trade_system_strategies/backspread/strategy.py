"""Call backspread backtest strategy.

Sells 1 ATM/ITM call and buys 2 OTM calls (1:2 ratio) on the same expiry, profiting
from a large upside move. Scaffold: leg selection is in
:mod:`~trade_system_strategies.backspread.signals`; submit/reconcile is stubbed.
"""

from nautilus_trader.model.data import Bar
from nautilus_trader.trading.strategy import Strategy

from trade_system_strategies.backspread.config import BackspreadConfig


class BackspreadStrategy(Strategy):
    """Backtest strategy for a call backspread.

    Args:
        config: The backspread strategy configuration.

    """

    def __init__(self, config: BackspreadConfig) -> None:
        """Initialize the backspread strategy with its config."""
        super().__init__(config)
        self._config: BackspreadConfig = config

    def on_start(self) -> None:
        """Subscribe to the underlying and option chain on startup."""
        # TODO: subscribe to the option chain for the underlying.

    def on_bar(self, bar: Bar) -> None:
        """Entry/roll decisions on each underlying bar."""
        # TODO: drive backspread entry and rolling from bar events.

    def on_order_filled(self, event) -> None:
        """Reconcile each leg fill into the active :class:`LegGroup`."""
        # TODO: map event.client_order_id -> LegGroup.apply_fill(...).
