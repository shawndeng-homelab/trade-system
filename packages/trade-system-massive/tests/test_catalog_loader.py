"""Tests for the Massive.com catalog loader.

Uses ``types.SimpleNamespace`` fakes for Massive response objects (no network).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import trade_system_massive.catalog_loader as cl_mod
from trade_system_massive.catalog_loader import _FakeClock
from trade_system_massive.catalog_loader import download_option_chain
from trade_system_massive.catalog_loader import make_client


# --- _FakeClock ------------------------------------------------------------------------


def test_fake_clock_returns_fixed_timestamp():
    """_FakeClock returns the timestamp it was initialized with."""
    clock = _FakeClock(ts_ns=1_700_000_000_000_000_000)
    assert clock.timestamp_ns() == 1_700_000_000_000_000_000


def test_fake_clock_default_timestamp():
    """_FakeClock defaults to a sensible nonzero timestamp."""
    clock = _FakeClock()
    assert clock.timestamp_ns() > 0


# --- make_client -----------------------------------------------------------------------


def test_make_client_returns_client_and_limiter():
    """make_client returns a (RESTClient, TokenBucketRateLimiter) tuple."""
    client, limiter = make_client(api_key="test_key")
    assert client is not None
    assert limiter is not None


# --- download_option_chain (unit test with fakes) -------------------------------------


def test_download_option_chain_parses_contracts():
    """download_option_chain parses Massive contracts into OptionContract instruments."""
    # Create a fake Massive options contract
    fake_contract = SimpleNamespace(
        ticker="O:SPY251219C00430000",
        expiration_date="2025-12-19",
        strike_price=430.0,
        contract_type="call",
        underlying_ticker="SPY",
        primary_exchange="OPRA",
        exercise_style="american",
        cfi="OCASPS",
        shares_per_contract=100,
    )

    # Mock the rate_limited_call to return our fake contracts as an awaitable
    original_fn = cl_mod.rate_limited_call

    async def fake_rate_limited_call(*args, **kwargs):
        return [fake_contract]

    cl_mod.rate_limited_call = fake_rate_limited_call

    try:
        # Mock catalog
        mock_catalog = MagicMock()

        # Run the download
        asyncio.run(
            download_option_chain(
                MagicMock(),  # client
                MagicMock(),  # limiter
                mock_catalog,
                underlying="SPY",
            )
        )

        # Verify instruments were written to catalog
        assert mock_catalog.write_data.called
        written = mock_catalog.write_data.call_args[0][0]
        assert len(written) == 1
        assert written[0].strike_price.as_double() == 430.0
    finally:
        cl_mod.rate_limited_call = original_fn
