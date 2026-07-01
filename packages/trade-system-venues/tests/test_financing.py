"""Scaffold smoke tests for the shared financing settlement machinery."""

from nautilus_trader.common.actor import Actor
from trade_system_venues.binance.funding import BinanceFundingActor
from trade_system_venues.core.financing import FinancingSettlementActor
from trade_system_venues.ibkr.financing import IBKRFinancingActor


def test_financing_actor_is_actor():
    """The base settlement class is a NautilusTrader Actor."""
    assert issubclass(FinancingSettlementActor, Actor)


def test_venue_actors_share_base():
    """Both venue financing actors reuse the shared settlement base."""
    assert issubclass(BinanceFundingActor, FinancingSettlementActor)
    assert issubclass(IBKRFinancingActor, FinancingSettlementActor)
