"""Tests for the multi-leg state machine in ``shared.legs``."""

from decimal import Decimal

from trade_system_strategies.shared.legs import LegGroup
from trade_system_strategies.shared.legs import LegSpec


def test_leg_spec_signed_quantity():
    """BUY legs are positive, SELL legs negative."""
    buy = LegSpec("SPY.ARCA", "BUY", Decimal("2"))
    sell = LegSpec("SPY.ARCA", "SELL", Decimal("1"))
    assert buy.signed_quantity == Decimal("2")
    assert sell.signed_quantity == Decimal("-1")


def test_leg_fill_accumulates_average_price():
    """Two partial fills blend into a volume-weighted average price."""
    leg = LegSpec("AAPL.NASDAQ", "BUY", Decimal("10"))
    group = LegGroup(name="pmcc")
    group.add_leg(leg, "order-1")
    group.apply_fill("order-1", Decimal("4"), Decimal("5.00"))
    group.apply_fill("order-1", Decimal("6"), Decimal("6.00"))
    # avg = (4*5 + 6*6) / 10 = 5.60
    assert group.legs[0].avg_fill_price == Decimal("5.60")
    assert group.legs[0].filled_qty == Decimal("10")
    assert group.legs[0].is_complete is True


def test_group_complete_and_net_cost():
    """A filled debit combo reports positive net cost (premium paid)."""
    group = LegGroup(name="pmcc")
    group.add_leg(LegSpec("LEAPS", "BUY", Decimal("1")), "buy-1")
    group.add_leg(LegSpec("SHORT", "SELL", Decimal("1")), "sell-1")
    group.apply_fill("buy-1", Decimal("1"), Decimal("20.00"))
    group.apply_fill("sell-1", Decimal("1"), Decimal("3.00"))
    # net = +1*20 + (-1)*3 = 17 debit
    assert group.is_complete is True
    assert group.net_cost == Decimal("17.00")


def test_group_incomplete_when_a_leg_partial():
    """The group is not complete until every leg is fully filled."""
    group = LegGroup(name="pmcc")
    group.add_leg(LegSpec("LEAPS", "BUY", Decimal("2")), "buy-1")
    group.apply_fill("buy-1", Decimal("1"), Decimal("20.00"))
    assert group.is_complete is False
