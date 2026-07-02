"""Call backspread strategy configuration."""



from decimal import Decimal

from nautilus_trader.config import StrategyConfig


class BackspreadConfig(StrategyConfig, frozen=True):
    """Configuration for the call backspread.

    A call backspread sells 1 ATM/ITM call and buys 2 OTM calls (1:2 ratio),
    profiting from a large upside move with defined downside risk.

    Attributes:
        underlying: The underlying instrument id.
        short_target_delta: Target absolute delta for the short (ATM/ITM) leg.
        long_target_delta: Target absolute delta for each long (OTM) leg.
        ratio: Long contracts per short contract (default 2 for a 1:2 backspread).
        delta_tolerance: Max acceptable delta gap when selecting legs.

    """

    underlying: str
    short_target_delta: Decimal = Decimal("0.50")
    long_target_delta: Decimal = Decimal("0.30")
    ratio: int = 2
    delta_tolerance: Decimal | None = None
