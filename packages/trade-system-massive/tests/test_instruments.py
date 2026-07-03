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
from nautilus_trader.model.instruments import OptionContract
from trade_system_massive.instruments import MassiveInstrumentProvider


class _FakeClock:
    """A clock stub returning a fixed nanosecond timestamp."""

    def __init__(self, ts_ns: int = 1_700_000_000_000_000_000) -> None:
        self._ts = ts_ns

    def timestamp_ns(self) -> int:
        return self._ts


@pytest.fixture()
def provider() -> MassiveInstrumentProvider:
    """Return a provider with a dummy client/limiter and a fixed clock."""
    # `_parse_equity` / `_parse_options_contract` are pure and never touch the client
    # or limiter, so None is safe here.
    return MassiveInstrumentProvider(
        client=None,
        rate_limiter=None,
        clock=_FakeClock(),
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
