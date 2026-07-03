"""Tests for the Massive instrument provider's parsing logic.

Parsing is tested directly with ``types.SimpleNamespace`` fakes, matching the
convention documented in ``parsing.py`` (real Massive models need no network).
"""

import datetime as dt
from types import SimpleNamespace

import pytest
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.instruments import OptionContract
from trade_system_massive.instruments import MassiveInstrumentProvider
from trade_system_massive.instruments import MassiveInstrumentProviderConfig


class _FakeClock:
    """A clock stub returning a fixed nanosecond timestamp."""

    def __init__(self, ts_ns: int = 1_700_000_000_000_000_000) -> None:
        self._ts = ts_ns

    def timestamp_ns(self) -> int:
        return self._ts


@pytest.fixture()
def provider() -> MassiveInstrumentProvider:
    """Return a provider with a dummy client/limiter and a fixed clock."""
    # `_parse_equity` / `_parse_options_contract` / `_parse_futures_contract` are pure
    # and never touch the client or limiter, so None is safe here.
    return MassiveInstrumentProvider(
        client=None,
        rate_limiter=None,
        clock=_FakeClock(),
    )


def _provider_with(config: MassiveInstrumentProviderConfig) -> MassiveInstrumentProvider:
    """Return a provider carrying a custom config (for override-driven tests)."""
    return MassiveInstrumentProvider(
        client=None,
        rate_limiter=None,
        clock=_FakeClock(),
        config=config,
    )


# --- equity ---------------------------------------------------------------------------


def test_parse_equity_builds_equity_with_defaults(provider: MassiveInstrumentProvider) -> None:
    """An equity is built with the US-default $0.01 tick and 100-share lot."""
    details = SimpleNamespace(
        ticker="AAPL",
        currency_name="USD",
        primary_exchange="XNAS",
        name="Apple Inc.",
        type="CS",
        market="stocks",
        list_date="2024-01-02",
        cik=None,
        composite_figi=None,
    )
    instrument_id = InstrumentId(Symbol("AAPL"), Venue("XNAS"))

    equity = provider._parse_equity(instrument_id, details)

    assert isinstance(equity, Equity)
    assert equity.id == instrument_id
    assert str(equity.quote_currency) == "USD"
    assert equity.price_precision == 2
    assert str(equity.price_increment) == "0.01"
    assert str(equity.lot_size) == "100"
    assert equity.raw_symbol == Symbol("AAPL")
    assert equity.info["primary_exchange"] == "XNAS"


def test_parse_equity_falls_back_to_usd_when_currency_missing(provider: MassiveInstrumentProvider) -> None:
    """A missing currency_name defaults to USD rather than raising."""
    details = SimpleNamespace(ticker="FOO", currency_name=None, primary_exchange=None)

    equity = provider._parse_equity(InstrumentId(Symbol("FOO"), Venue("XNAS")), details)

    assert str(equity.quote_currency) == "USD"


# --- option contract ------------------------------------------------------------------


def test_parse_options_contract_builds_call(provider: MassiveInstrumentProvider) -> None:
    """A call option contract is parsed with correct kind, strike, and multiplier."""
    contract = SimpleNamespace(
        ticker="O:AAPL251219C00150000",
        underlying_ticker="AAPL",
        contract_type="call",
        strike_price=150.0,
        expiration_date="2025-12-19",
        exercise_style="american",
        shares_per_contract=100,
        primary_exchange="OPRA",
        cfi="OCAS",
    )

    option = provider._parse_options_contract(contract)

    assert isinstance(option, OptionContract)
    assert option.asset_class == AssetClass.EQUITY
    assert option.option_kind == OptionKind.CALL
    assert option.underlying == "AAPL"
    assert str(option.strike_price) == "150.0"
    assert str(option.multiplier) == "100"
    assert option.id.venue == Venue("OPRA")
    # Expiration 2025-12-19 16:00 ET ~ 20:00 UTC.
    expected_exp = int(dt.datetime(2025, 12, 19, 20, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
    assert option.expiration_ns == expected_exp
    # Activation leads expiration by ~90 days.
    assert option.activation_ns < option.expiration_ns
    assert option.info["exercise_style"] == "american"


def test_parse_options_contract_put_kind(provider: MassiveInstrumentProvider) -> None:
    """A ``contract_type`` starting with 'p' maps to PUT."""
    contract = SimpleNamespace(
        ticker="O:AAPL251219P00150000",
        underlying_ticker="AAPL",
        contract_type="put",
        strike_price=150.0,
        expiration_date="2025-12-19",
        exercise_style="american",
        shares_per_contract=100,
        primary_exchange="OPRA",
        cfi=None,
    )

    option = provider._parse_options_contract(contract)

    assert option.option_kind == OptionKind.PUT


def test_parse_options_contract_skips_unparseable_expiration(provider: MassiveInstrumentProvider) -> None:
    """An option whose expiration cannot be parsed is skipped (returns None)."""
    contract = SimpleNamespace(
        ticker="O:AAPL000000C00150000",
        underlying_ticker="AAPL",
        contract_type="call",
        strike_price=150.0,
        expiration_date="not-a-date",
        exercise_style="american",
        shares_per_contract=100,
        primary_exchange="OPRA",
        cfi=None,
    )

    assert provider._parse_options_contract(contract) is None


# --- futures contract -----------------------------------------------------------------


def _futures_contract_fake(**overrides) -> SimpleNamespace:
    """Return a minimal ``FuturesContract`` fake with sane CLZ25 defaults."""
    base = {
        "ticker": "CLZ25",
        "product_code": "CL",
        "trading_venue": "XNYM",
        "name": "Crude Oil Futures",
        "type": "single",
        "date": "2025-01-15",
        "active": True,
        "first_trade_date": "2025-06-20",
        "last_trade_date": "2025-12-19",
        "days_to_maturity": 120,
        "min_order_quantity": 1,
        "max_order_quantity": 9999,
        "settlement_date": "2025-12-19",
        "settlement_tick_size": 0.01,
        "spread_tick_size": 0.01,
        "trade_tick_size": 0.01,
        "group_code": "CL",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_parse_futures_contract_builds_commodity_default(provider: MassiveInstrumentProvider) -> None:
    """A futures contract is built with COMMODITY default, venue from trading_venue."""
    contract = _futures_contract_fake()

    future = provider._parse_futures_contract(contract)

    assert isinstance(future, FuturesContract)
    assert future.asset_class == AssetClass.COMMODITY
    assert future.id == InstrumentId(Symbol("CLZ25"), Venue("XNYM"))
    assert future.underlying == "CL"
    assert str(future.multiplier) == "1"
    assert str(future.lot_size) == "1"
    assert future.price_precision == 2
    assert str(future.price_increment) == "0.01"
    assert str(future.quote_currency) == "USD"
    expected_exp = int(dt.datetime(2025, 12, 19, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
    assert future.expiration_ns == expected_exp
    expected_act = int(dt.datetime(2025, 6, 20, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
    assert future.activation_ns == expected_act
    assert future.info["product_code"] == "CL"
    assert future.info["trade_tick_size"] == 0.01


def test_parse_futures_contract_applies_asset_class_override() -> None:
    """A product listed in `futures_asset_class_overrides` maps to that AssetClass."""
    cfg = MassiveInstrumentProviderConfig(futures_asset_class_overrides={"ES": "EQUITY"})
    provider = _provider_with(cfg)
    contract = _futures_contract_fake(ticker="ESZ4", product_code="ES", trading_venue="XCME")

    future = provider._parse_futures_contract(contract)

    assert future.asset_class == AssetClass.EQUITY
    assert future.id.venue == Venue("XCME")


def test_parse_futures_contract_applies_multiplier_override() -> None:
    """A product listed in `futures_multipliers` uses that multiplier."""
    cfg = MassiveInstrumentProviderConfig(futures_multipliers={"ES": 50})
    provider = _provider_with(cfg)
    contract = _futures_contract_fake(ticker="ESZ4", product_code="ES")

    future = provider._parse_futures_contract(contract)

    assert str(future.multiplier) == "50"


def test_parse_futures_contract_skips_combo(provider: MassiveInstrumentProvider) -> None:
    """A ``type='combo'`` contract is skipped (returns None)."""
    contract = _futures_contract_fake(type="combo")

    assert provider._parse_futures_contract(contract) is None


def test_parse_futures_contract_skips_unparseable_expiration(provider: MassiveInstrumentProvider) -> None:
    """A futures contract with no parseable expiration date is skipped."""
    contract = _futures_contract_fake(
        settlement_date="not-a-date",
        last_trade_date=None,
        date=None,
    )

    assert provider._parse_futures_contract(contract) is None


def test_parse_futures_contract_falls_back_to_last_trade_date(provider: MassiveInstrumentProvider) -> None:
    """When `settlement_date` is missing, `last_trade_date` is used for expiration."""
    contract = _futures_contract_fake(settlement_date=None, last_trade_date="2025-12-19")

    future = provider._parse_futures_contract(contract)

    expected_exp = int(dt.datetime(2025, 12, 19, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
    assert future.expiration_ns == expected_exp


def test_parse_futures_contract_default_venue_when_missing(provider: MassiveInstrumentProvider) -> None:
    """A missing `trading_venue` falls back to DEFAULT_FUTURES_VENUE (XCBT)."""
    contract = _futures_contract_fake(trading_venue=None)

    future = provider._parse_futures_contract(contract)

    assert future.id.venue == Venue("XCBT")


def test_parse_futures_contract_price_precision_from_tick_size(provider: MassiveInstrumentProvider) -> None:
    """`price_precision` is derived from `trade_tick_size` decimal places."""
    contract = _futures_contract_fake(trade_tick_size=0.0001)

    future = provider._parse_futures_contract(contract)

    assert future.price_precision == 4
    assert str(future.price_increment) == "0.0001"


def test_parse_futures_contract_activation_zero_when_first_trade_missing(
    provider: MassiveInstrumentProvider,
) -> None:
    """A missing `first_trade_date` yields activation_ns == 0 (no 90-day lead hack)."""
    contract = _futures_contract_fake(first_trade_date=None)

    future = provider._parse_futures_contract(contract)

    assert future.activation_ns == 0
