"""Nautilus instrument provider for the Massive.com (Polygon-compatible) API.

Loads :class:`~nautilus_trader.model.instruments.Equity` and
:class:`~nautilus_trader.model.instruments.OptionContract` definitions from the Massive
REST client. The synchronous Massive client is wrapped through
:func:`~trade_system_massive.rate_limiter.rate_limited_call` so every call honours the
adapter's token-bucket limiter.

Loading is on-demand-first (``load_ids_async`` resolves each instrument id individually);
full option-chain fetch via ``options_underlyings`` runs only when explicitly configured,
which keeps free-tier request budgets under control.
"""

import asyncio
from decimal import Decimal

from massive import RESTClient
from massive.exceptions import BadResponse
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity

from trade_system_massive.common import clamp_to_9dp
from trade_system_massive.common import is_future_ticker
from trade_system_massive.common import is_option_ticker
from trade_system_massive.common import option_kind_from_contract_type
from trade_system_massive.common import ticker_to_venue
from trade_system_massive.constants import DEFAULT_FUTURES_VENUE
from trade_system_massive.parsing import decimal_or_default
from trade_system_massive.parsing import parse_date_to_start_ns
from trade_system_massive.parsing import parse_expiration_ns
from trade_system_massive.rate_limiter import TokenBucketRateLimiter
from trade_system_massive.rate_limiter import rate_limited_call


# Massive does not expose a per-instrument tick size; US equity/options trade on a
# $0.01 minimum increment. Override via `info` if a finer tick is known.
DEFAULT_PRICE_PRECISION: int = 2
DEFAULT_PRICE_INCREMENT: str = "0.01"
# Standard US equity option contract size; Massive reports it per-contract.
DEFAULT_SHARES_PER_CONTRACT: int = 100
# Futures contract multiplier default when `futures_multipliers` has no override for
# the product. Massive's contract endpoint does not expose the multiplier (e.g. ES=50,
# CL=1000); override per product via `MassiveInstrumentProviderConfig.futures_multipliers`.
DEFAULT_FUTURES_MULTIPLIER: int = 1
# Approximate activation lead time (days) when Massive gives none; matches the IBKR
# adapter convention. TODO: replace with a real listing/activation date when exposed.
DEFAULT_ACTIVATION_LEAD_DAYS: int = 90
DAY_NS: int = 86_400 * 1_000_000_000


class MassiveInstrumentProviderConfig(InstrumentProviderConfig, frozen=True, kw_only=True):
    """Configuration for :class:`MassiveInstrumentProvider`.

    Parameters
    ----------
    options_underlyings : set[str], optional
        The equity underlyings whose full option chains to preload in ``load_all_async``.
        Leave empty to load options on demand via ``load_ids_async`` (free-tier friendly).
    pagination_limit : int, default 50000
        The page size passed to ``list_options_contracts`` / ``list_futures_contracts``
        when preloading chains.
    futures_product_codes : set[str], optional
        The futures product codes (e.g. ``{"ES", "CL", "ZN"}``) whose contracts this
        adapter should treat as futures. Required to dispatch bare futures tickers
        (e.g. ``ESZ4``) away from the stock path; also preloaded in ``load_all_async``.
    futures_asset_class_overrides : dict[str, str], optional
        Per-product-code override of the Nautilus ``AssetClass`` enum *name* (e.g.
        ``{"ES": "EQUITY", "6E": "FX", "ZN": "DEBT"}``). Products not listed default to
        ``COMMODITY``. Values are enum-name strings (not ints) so they survive config
        serialization.
    futures_multipliers : dict[str, int], optional
        Per-product-code contract multiplier (e.g. ``{"ES": 50, "CL": 1000}``). Massive's
        contract endpoint does not expose the multiplier; unlisted products default to 1.

    """

    options_underlyings: set[str] | None = None
    pagination_limit: int = 50_000
    futures_product_codes: set[str] | None = None
    futures_asset_class_overrides: dict[str, str] | None = None
    futures_multipliers: dict[str, int] | None = None


class MassiveInstrumentProvider(InstrumentProvider):
    """Provides Nautilus instrument definitions from Massive.com.

    Parameters
    ----------
    client : RESTClient
        The Massive.com synchronous REST client.
    rate_limiter : TokenBucketRateLimiter
        The limiter gating every REST call.
    clock : LiveClock
        The live clock used for instrument timestamps.
    config : MassiveInstrumentProviderConfig, optional
        The instrument provider configuration.

    """

    def __init__(
        self,
        client: RESTClient,
        rate_limiter: TokenBucketRateLimiter,
        clock: LiveClock,
        config: MassiveInstrumentProviderConfig | None = None,
    ) -> None:
        """Initialize the provider with its client, limiter, clock, and config."""
        super().__init__(config=config or MassiveInstrumentProviderConfig())
        self._client = client
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._config: MassiveInstrumentProviderConfig = config or MassiveInstrumentProviderConfig()

    # ------------------------------------------------------------------ loading

    async def load_all_async(self, filters: dict | None = None) -> None:
        """Preload option chains and/or futures chains for every configured product.

        Option chains load only when ``options_underlyings`` is set; futures chains
        load only when ``futures_product_codes`` is set. Equities are never bulk-loaded
        (Massive has no "list all equities" endpoint suitable for a free tier); load
        them individually via :meth:`load_ids_async`.

        """
        underlyings = self._config.options_underlyings
        futures_codes = self._config.futures_product_codes
        if not underlyings and not futures_codes:
            return
        tasks = [self._load_option_chain(u) for u in sorted(underlyings or [])]
        tasks += [self._load_futures_chain(pc) for pc in sorted(futures_codes or [])]
        await asyncio.gather(*tasks)

    async def _load_option_chain(self, underlying: str) -> None:
        """Page through ``list_options_contracts`` for one underlying and add each."""
        limit = self._config.pagination_limit
        # The Massive client auto-paginates when pagination=True (set in the factory);
        # we still pass `limit` as the page size and iterate the resulting generator.
        contracts = await rate_limited_call(
            self._rate_limiter,
            self._client.list_options_contracts,
            underlying_ticker=underlying,
            expired=False,
            limit=limit,
        )
        for contract in contracts:
            instrument = self._parse_options_contract(contract)
            if instrument is not None:
                self.add(instrument)

    async def _load_futures_chain(self, product_code: str) -> None:
        """Page through ``list_futures_contracts`` for one product and add each.

        Combos (``type='combo'``) are skipped server-side via ``type='single'``; any
        combo that still slips through is dropped in :meth:`_parse_futures_contract`.

        """
        limit = self._config.pagination_limit
        contracts = await rate_limited_call(
            self._rate_limiter,
            self._client.list_futures_contracts,
            product_code=product_code,
            active=True,
            type="single",
            limit=limit,
        )
        for contract in contracts:
            instrument = self._parse_futures_contract(contract)
            if instrument is not None:
                self.add(instrument)

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """Resolve and load each instrument id individually (on-demand)."""
        if not instrument_ids:
            return
        await asyncio.gather(*(self._load_one(iid) for iid in instrument_ids))

    async def _load_one(self, instrument_id: InstrumentId) -> None:
        """Fetch and add a single instrument by its id (option, future, or equity)."""
        ticker = instrument_id.symbol.value
        try:
            if is_option_ticker(ticker):
                contract = await rate_limited_call(
                    self._rate_limiter,
                    self._client.get_options_contract,
                    ticker,
                )
                instrument = self._parse_options_contract(contract)
            elif is_future_ticker(ticker, self._config.futures_product_codes):
                contracts = await rate_limited_call(
                    self._rate_limiter,
                    self._client.list_futures_contracts,
                    ticker=ticker,
                )
                # `list_futures_contracts` returns an iterator; take the first match.
                contract = next(iter(contracts), None)
                instrument = self._parse_futures_contract(contract) if contract else None
            else:
                details = await rate_limited_call(
                    self._rate_limiter,
                    self._client.get_ticker_details,
                    ticker,
                )
                instrument = self._parse_equity(instrument_id, details)
        except BadResponse as exc:
            self._log.error(f"Could not load instrument {instrument_id}: {exc}")
            return
        if instrument is not None:
            self.add(instrument)

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def _instrument_id_for(
        ticker: str,
        equity_exchange: str | None = None,
        futures_venue: str | None = None,
        is_future: bool = False,
    ) -> InstrumentId:
        """Build a Nautilus instrument id from a Massive ticker and exchange."""
        return InstrumentId(Symbol(ticker), ticker_to_venue(ticker, equity_exchange, futures_venue, is_future))

    def _parse_equity(self, instrument_id: InstrumentId, details) -> Equity:
        """Build an :class:`Equity` from a Massive ``TickerDetails``.

        Massive reports no tick size; the US default of $0.01 is assumed. Override the
        price increment via the instrument's ``info`` if a finer tick is known.

        """
        currency_name = getattr(details, "currency_name", None) or "USD"
        currency = Currency.from_str(str(currency_name).upper())
        ts = self._clock.timestamp_ns()
        exchange = getattr(details, "primary_exchange", None)
        # If the requested venue differs from the ticker's primary exchange (e.g. an
        # explicit XNAS override), keep the requested id; otherwise normalise to it.
        if exchange and instrument_id.venue.value != exchange:
            instrument_id = self._instrument_id_for(instrument_id.symbol.value, equity_exchange=exchange)
        return Equity(
            instrument_id=instrument_id,
            raw_symbol=Symbol(getattr(details, "ticker", instrument_id.symbol.value)),
            currency=currency,
            price_precision=DEFAULT_PRICE_PRECISION,
            price_increment=Price.from_str(DEFAULT_PRICE_INCREMENT),
            lot_size=Quantity.from_int(100),
            ts_event=ts,
            ts_init=ts,
            info={
                "name": getattr(details, "name", None),
                "type": getattr(details, "type", None),
                "market": getattr(details, "market", None),
                "primary_exchange": exchange,
                "list_date": getattr(details, "list_date", None),
                "cik": getattr(details, "cik", None),
                "composite_figi": getattr(details, "composite_figi", None),
            },
        )

    def _parse_futures_contract(self, contract) -> FuturesContract | None:
        """Build a :class:`FuturesContract` from a Massive ``FuturesContract``.

        v1 supports ``type='single'`` contracts only; combos are skipped with a
        warning. Massive's contract endpoint exposes real tick sizes
        (``trade_tick_size``) but not the contract multiplier, so the multiplier
        defaults to 1 unless overridden via ``futures_multipliers``. Asset class
        defaults to ``COMMODITY`` unless overridden via ``futures_asset_class_overrides``.

        """
        ticker = getattr(contract, "ticker", None)
        if not ticker:
            return None
        ctype = getattr(contract, "type", "single")
        if ctype and ctype != "single":
            self._log.warning(f"Skipping futures contract {ticker}: type={ctype!r} (combo not supported in v1)")
            return None

        product_code = getattr(contract, "product_code", None) or ""
        venue_mic = getattr(contract, "trading_venue", None) or DEFAULT_FUTURES_VENUE
        instrument_id = self._instrument_id_for(ticker, futures_venue=venue_mic, is_future=True)

        overrides = self._config.futures_asset_class_overrides or {}
        asset_class_name = overrides.get(product_code, "COMMODITY")
        try:
            asset_class = AssetClass[asset_class_name]
        except KeyError:
            self._log.warning(
                f"Futures {ticker}: unknown asset class {asset_class_name!r}; defaulting to COMMODITY",
            )
            asset_class = AssetClass.COMMODITY

        # Expiration: settlement_date → last_trade_date → date, parsed to 00:00 UTC ns.
        exp_ns = parse_date_to_start_ns(
            getattr(contract, "settlement_date", None)
            or getattr(contract, "last_trade_date", None)
            or getattr(contract, "date", None),
        )
        if exp_ns == 0:
            self._log.warning(f"Futures {ticker} has unparseable expiration; skipping")
            return None
        activation_ns = parse_date_to_start_ns(getattr(contract, "first_trade_date", None))

        multipliers = self._config.futures_multipliers or {}
        mult_int = int(multipliers.get(product_code, DEFAULT_FUTURES_MULTIPLIER))
        multiplier = Quantity.from_int(mult_int)

        moq = getattr(contract, "min_order_quantity", None)
        lot = Quantity.from_str(clamp_to_9dp(moq)) if moq else Quantity.from_int(DEFAULT_FUTURES_MULTIPLIER)

        tick_size = getattr(contract, "trade_tick_size", None)
        inc_str = clamp_to_9dp(tick_size) if tick_size is not None else DEFAULT_PRICE_INCREMENT
        price_increment = Price.from_str(inc_str)
        price_precision = min(9, max(0, -Decimal(inc_str).as_tuple().exponent))

        ts = self._clock.timestamp_ns()
        return FuturesContract(
            instrument_id=instrument_id,
            raw_symbol=Symbol(ticker),
            asset_class=asset_class,
            currency=Currency.from_str("USD"),
            price_precision=price_precision,
            price_increment=price_increment,
            multiplier=multiplier,
            lot_size=lot,
            underlying=product_code or getattr(contract, "group_code", "") or "",
            activation_ns=activation_ns,
            expiration_ns=exp_ns,
            ts_event=ts,
            ts_init=ts,
            exchange=venue_mic,
            info={
                "product_code": product_code,
                "group_code": getattr(contract, "group_code", None),
                "name": getattr(contract, "name", None),
                "type": ctype,
                "active": getattr(contract, "active", None),
                "days_to_maturity": getattr(contract, "days_to_maturity", None),
                "settlement_date": getattr(contract, "settlement_date", None),
                "first_trade_date": getattr(contract, "first_trade_date", None),
                "last_trade_date": getattr(contract, "last_trade_date", None),
                "min_order_quantity": moq,
                "max_order_quantity": getattr(contract, "max_order_quantity", None),
                "settlement_tick_size": getattr(contract, "settlement_tick_size", None),
                "spread_tick_size": getattr(contract, "spread_tick_size", None),
                "trade_tick_size": tick_size,
            },
        )

    def _parse_options_contract(self, contract) -> OptionContract | None:
        """Build an :class:`OptionContract` from a Massive ``OptionsContract``."""
        ticker = getattr(contract, "ticker", None)
        if not ticker:
            return None
        instrument_id = self._instrument_id_for(ticker)
        expiration_ns = parse_expiration_ns(getattr(contract, "expiration_date", None))
        if expiration_ns == 0:
            self._log.warning(f"Option {ticker} has unparseable expiration; skipping")
            return None
        activation_ns = max(0, expiration_ns - DEFAULT_ACTIVATION_LEAD_DAYS * DAY_NS)
        shares = int(getattr(contract, "shares_per_contract", 0) or DEFAULT_SHARES_PER_CONTRACT)
        multiplier = Quantity.from_int(shares)
        strike = decimal_or_default(getattr(contract, "strike_price", None), None)
        ts = self._clock.timestamp_ns()
        return OptionContract(
            instrument_id=instrument_id,
            raw_symbol=Symbol(ticker),
            asset_class=AssetClass.EQUITY,
            currency=Currency.from_str("USD"),
            price_precision=DEFAULT_PRICE_PRECISION,
            price_increment=Price.from_str(DEFAULT_PRICE_INCREMENT),
            multiplier=multiplier,
            lot_size=multiplier,
            underlying=getattr(contract, "underlying_ticker", "") or "",
            option_kind=option_kind_from_contract_type(getattr(contract, "contract_type", None)),
            strike_price=Price.from_str(str(strike)),
            activation_ns=activation_ns,
            expiration_ns=expiration_ns,
            ts_event=ts,
            ts_init=ts,
            exchange=getattr(contract, "primary_exchange", None),
            info={
                "exercise_style": getattr(contract, "exercise_style", None),
                "cfi": getattr(contract, "cfi", None),
                "shares_per_contract": shares,
            },
        )

    # The base InstrumentProvider exposes find/get_all/add/currencies; no overrides needed.


__all__ = [
    "DEFAULT_ACTIVATION_LEAD_DAYS",
    "DEFAULT_FUTURES_MULTIPLIER",
    "DEFAULT_PRICE_INCREMENT",
    "DEFAULT_PRICE_PRECISION",
    "DEFAULT_SHARES_PER_CONTRACT",
    "MassiveInstrumentProvider",
    "MassiveInstrumentProviderConfig",
]
