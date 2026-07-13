"""PMCC (Poor Man's Covered Call) backtest strategy.

Long a deep-ITM LEAPS call (far expiry, ~0.8 delta) + short a near-term OTM call
(~0.3 delta). Each leg is submitted as a separate order and reconciled through
:class:`~trade_system_strategies.shared.legs.LegGroup`.

Lifecycle states::

    FLAT → ENTERING → ACTIVE → (ROLLING_SHORT | ROLLING_LEAPS) → ACTIVE → EXITING → FLAT

Decision logic lives in :mod:`~trade_system_strategies.pmcc.signals`; this module is
the NautilusTrader glue that wires signals to the engine.
"""

from decimal import Decimal
from enum import Enum

from nautilus_trader.common.enums import LogColor
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.trading.strategy import Strategy

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.signals import PMCCAction
from trade_system_strategies.pmcc.signals import pmcc_entry_decision
from trade_system_strategies.pmcc.signals import pmcc_leaps_decision
from trade_system_strategies.pmcc.signals import pmcc_roll_config_from_pmcc_config
from trade_system_strategies.pmcc.signals import pmcc_short_call_decision
from trade_system_strategies.pmcc.signals import select_leaps_roll_target
from trade_system_strategies.pmcc.signals import select_short_call_roll_target
from trade_system_strategies.shared.greeks import approx_call_delta
from trade_system_strategies.shared.legs import LegGroup
from trade_system_strategies.shared.legs import LegSpec
from trade_system_strategies.shared.management import PositionSnapshot
from trade_system_strategies.shared.management import RollWhenConfig
from trade_system_strategies.shared.option_pricing import bs_call_price
from trade_system_strategies.shared.selection import OptionCandidate
from trade_system_strategies.shared.selection import SelectionConfig
from trade_system_strategies.shared.selection import select_short_option
from trade_system_strategies.shared.sizing import TradeStats


class PMCCState(Enum):
    """Internal state machine for the PMCC strategy."""

    FLAT = "FLAT"
    ENTERING = "ENTERING"
    ACTIVE = "ACTIVE"
    ROLLING_SHORT = "ROLLING_SHORT"
    ROLLING_LEAPS = "ROLLING_LEAPS"
    EXITING = "EXITING"


class PMCCStrategy(Strategy):
    """Backtest strategy for a Poor Man's Covered Call.

    Manages the full PMCC lifecycle: entry (BUY LEAPS + SELL near-term call),
    short-call rolling, LEAPS rolling, and exit. Each phase is driven by pure
    decision functions in :mod:`~trade_system_strategies.pmcc.signals`.

    Args:
        config: The PMCC strategy configuration.

    """

    def __init__(self, config: PMCCConfig) -> None:
        """Initialize the PMCC strategy with its config."""
        super().__init__(config)
        self._config: PMCCConfig = config

        # Parsed identifiers
        self._instrument_id = InstrumentId.from_str(config.underlying)
        if config.bar_type is not None:
            self._bar_type = BarType.from_str(config.bar_type)
        else:
            self._bar_type = None

        # Resolved instruments (populated in on_start)
        self._underlying_instrument: Instrument | None = None
        self._leaps_instrument: OptionContract | None = None
        self._short_instrument: OptionContract | None = None
        self._option_instruments: list[OptionContract] = []

        # Active position tracking
        self._leg_group: LegGroup | None = None
        self._roll_leg_group: LegGroup | None = None
        self._leaps_fill_price: Decimal = Decimal("0")
        self._short_fill_price: Decimal = Decimal("0")
        self._prior_short_strike: Decimal | None = None

        # State machine
        self._state: PMCCState = PMCCState.FLAT

        # Roll config (derived from PMCCConfig once)
        self._roll_config: RollWhenConfig = pmcc_roll_config_from_pmcc_config(config)

        # Trade statistics
        self._stats = TradeStats(window=30, min_sample=10)

        # Pending roll target (set when roll is initiated, consumed on fill)
        self._new_short_target: OptionCandidate | None = None
        self._new_leaps_target: OptionCandidate | None = None

    # ── NautilusTrader lifecycle ──────────────────────────────────────────

    def on_start(self) -> None:
        """Resolve the underlying instrument, subscribe to bars, and load option chain."""
        self._underlying_instrument = self.cache.instrument(self._instrument_id)
        if self._underlying_instrument is None:
            self.log.error(f"Could not find instrument for {self._instrument_id}")
            self.stop()
            return

        # Construct bar_type from underlying if not provided
        if self._bar_type is None:
            self._bar_type = BarType.from_str(
                f"{self._config.underlying}-1-HOUR-LAST-EXTERNAL",
            )

        self.subscribe_bars(self._bar_type)

        # Load option instruments from the cache (pre-loaded by the data catalog)
        self._option_instruments = self._load_option_instruments()
        self.log.info(
            f"PMCC started: underlying={self._config.underlying}, "
            f"leaps_delta={self._config.leaps_target_delta}, "
            f"short_delta={self._config.short_target_delta}, "
            f"options_loaded={len(self._option_instruments)}",
        )

    def on_bar(self, bar: Bar) -> None:
        """Drive the PMCC lifecycle on each underlying bar close."""
        spot = bar.close.as_decimal()

        if self._state == PMCCState.FLAT:
            self._handle_flat(spot, bar)
        elif self._state == PMCCState.ENTERING:
            self._handle_entering()
        elif self._state == PMCCState.ACTIVE:
            self._handle_active(spot, bar)
        elif self._state == PMCCState.ROLLING_SHORT:
            self._handle_rolling_short()
        elif self._state == PMCCState.ROLLING_LEAPS:
            self._handle_rolling_leaps()
        elif self._state == PMCCState.EXITING:
            self._handle_exiting()

    def on_order_filled(self, event) -> None:
        """Reconcile each leg fill into the active :class:`LegGroup`."""
        client_order_id = str(event.client_order_id)
        fill_qty = event.last_qty.as_decimal()
        fill_price = event.last_px.as_decimal()

        # Reconcile into the main leg group
        if self._leg_group is not None and self._leg_group.has_order(client_order_id):
            self._leg_group.apply_fill(client_order_id, fill_qty, fill_price)
            self._track_fill_prices(client_order_id, fill_price)

            if self._leg_group.is_complete:
                if self._state == PMCCState.ENTERING:
                    self._state = PMCCState.ACTIVE
                    self.log.info(
                        f"PMCC entry complete: net_cost={self._leg_group.net_cost}",
                        color=LogColor.GREEN,
                    )
                elif self._state == PMCCState.EXITING:
                    self._record_trade_stats()
                    self._reset_position()

        # Reconcile into the roll leg group
        if self._roll_leg_group is not None and self._roll_leg_group.has_order(client_order_id):
            self._roll_leg_group.apply_fill(client_order_id, fill_qty, fill_price)

            if self._roll_leg_group.is_complete:
                if self._state == PMCCState.ROLLING_SHORT:
                    self._complete_short_roll()
                elif self._state == PMCCState.ROLLING_LEAPS:
                    self._complete_leaps_roll()

    def on_position_closed(self, event) -> None:
        """Record the realized PnL of each closed trade into the accumulator."""
        pnl = event.realized_pnl.as_decimal()
        ret = Decimal(str(event.realized_return)) if hasattr(event, "realized_return") else None
        self._stats.record(pnl, ret)
        self.log.info(
            f"Position closed: pnl={pnl} | stats: n={self._stats.count}",
            color=LogColor.YELLOW,
        )

    def on_stop(self) -> None:
        """Optionally flatten all positions on stop."""
        if self._config.close_positions_on_stop:
            if self._leaps_instrument is not None:
                self.close_all_positions(self._leaps_instrument.id)
            if self._short_instrument is not None:
                self.close_all_positions(self._short_instrument.id)

    # ── State handlers ───────────────────────────────────────────────────

    def _handle_flat(self, spot: Decimal, bar: Bar) -> None:
        """Attempt PMCC entry when flat."""
        action = pmcc_entry_decision(
            has_active_position=self._leg_group is not None,
            has_pending_orders=self._state not in (PMCCState.FLAT,),
        )
        if action != PMCCAction.ENTER:
            return

        leaps_candidates = self._build_leaps_candidates(spot)
        short_candidates = self._build_short_candidates(spot)

        if not leaps_candidates or not short_candidates:
            self.log.debug("No eligible LEAPS or short call candidates")
            return

        leaps_cfg = SelectionConfig(
            right="C",
            target_dte=self._config.leaps_min_dte,
            target_delta=self._config.leaps_target_delta,
            max_dte=self._config.leaps_max_dte,
            spot=spot,
            delta_mode="near",
            delta_tolerance=Decimal("0.10"),
        )
        short_cfg = SelectionConfig(
            right="C",
            target_dte=self._config.short_min_dte,
            target_delta=self._config.short_target_delta,
            max_dte=self._config.short_max_dte,
            spot=spot,
        )

        leaps_pick = select_short_option(leaps_candidates, leaps_cfg)
        short_pick = select_short_option(short_candidates, short_cfg)

        if leaps_pick is None or short_pick is None:
            self.log.debug("No matching LEAPS or short call after filtering")
            return

        # Resolve instruments from cache
        leaps_inst = self.cache.instrument(InstrumentId.from_str(leaps_pick.instrument_id))
        short_inst = self.cache.instrument(InstrumentId.from_str(short_pick.instrument_id))

        if leaps_inst is None or short_inst is None:
            self.log.warning("Selected option instruments not found in cache")
            return

        # Build and submit orders
        self._submit_entry(leaps_pick, short_pick, leaps_inst, short_inst)

    def _handle_entering(self) -> None:
        """Wait for entry fills; log progress."""
        self.log.debug(
            f"Waiting for entry fills: complete={self._leg_group.is_complete if self._leg_group else 'N/A'}",
        )

    def _handle_active(self, spot: Decimal, bar: Bar) -> None:
        """Monitor the active PMCC position for roll/close opportunities."""
        # 1. Check short call roll/close
        short_snapshot = self._build_short_snapshot(spot)
        if short_snapshot is not None:
            short_action = pmcc_short_call_decision(short_snapshot, self._roll_config)

            if short_action == PMCCAction.ROLL_SHORT:
                self._initiate_short_roll(spot, bar)
                return
            if short_action == PMCCAction.CLOSE_SHORT:
                self._close_short_leg()
                return

        # 2. Check LEAPS roll
        leaps_info = self._build_leaps_info(spot)
        if leaps_info is not None:
            leaps_action = pmcc_leaps_decision(
                dte=leaps_info["dte"],
                delta=leaps_info["delta"],
                leaps_roll_when_dte=self._config.leaps_roll_when_dte,
                leaps_roll_when_delta_below=self._config.leaps_roll_when_delta_below,
            )
            if leaps_action == PMCCAction.ROLL_LEAPS:
                self._initiate_leaps_roll(spot, bar)
                return

    def _handle_rolling_short(self) -> None:
        """Wait for short call roll fills."""
        self.log.debug("Waiting for short call roll fills...")

    def _handle_rolling_leaps(self) -> None:
        """Wait for LEAPS roll fills."""
        self.log.debug("Waiting for LEAPS roll fills...")

    def _handle_exiting(self) -> None:
        """Wait for exit fills."""
        self.log.debug("Waiting for exit fills...")

    # ── Order submission helpers ─────────────────────────────────────────

    def _submit_entry(
        self,
        leaps_pick: OptionCandidate,
        short_pick: OptionCandidate,
        leaps_inst: Instrument,
        short_inst: Instrument,
    ) -> None:
        """Submit BUY LEAPS + SELL short call orders and create the LegGroup."""
        leaps_id = InstrumentId.from_str(leaps_pick.instrument_id)
        short_id = InstrumentId.from_str(short_pick.instrument_id)

        leaps_spec = LegSpec(
            instrument_id=leaps_pick.instrument_id,
            side="BUY",
            quantity=self._config.leaps_quantity,
        )
        short_spec = LegSpec(
            instrument_id=short_pick.instrument_id,
            side="SELL",
            quantity=self._config.short_quantity,
        )

        self._leg_group = LegGroup(name="pmcc_entry")

        # Submit LEAPS buy order
        leaps_order: MarketOrder = self.order_factory.market(
            instrument_id=leaps_id,
            order_side=OrderSide.BUY,
            quantity=leaps_inst.make_qty(self._config.leaps_quantity),
            time_in_force=TimeInForce.GTC,
        )
        self._leg_group.add_leg(leaps_spec, str(leaps_order.client_order_id))
        self.submit_order(leaps_order)

        # Submit short call sell order
        short_order: MarketOrder = self.order_factory.market(
            instrument_id=short_id,
            order_side=OrderSide.SELL,
            quantity=short_inst.make_qty(self._config.short_quantity),
            time_in_force=TimeInForce.GTC,
        )
        self._leg_group.add_leg(short_spec, str(short_order.client_order_id))
        self.submit_order(short_order)

        self._leaps_instrument = leaps_inst
        self._short_instrument = short_inst
        self._state = PMCCState.ENTERING
        self.log.info(
            f"PMCC entry submitted: LEAPS={leaps_pick.instrument_id}, SHORT={short_pick.instrument_id}",
        )

    def _close_short_leg(self) -> None:
        """Close the short call position (BUY to close)."""
        if self._short_instrument is None:
            return
        order: MarketOrder = self.order_factory.market(
            instrument_id=self._short_instrument.id,
            order_side=OrderSide.BUY,
            quantity=self._short_instrument.make_qty(self._config.short_quantity),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self.log.info(f"Closing short call: {self._short_instrument.id}")

    def _initiate_short_roll(self, spot: Decimal, bar: Bar) -> None:
        """Initiate a short call roll: close current, then open new."""
        if self._short_instrument is None:
            return

        candidates = self._build_short_candidates(spot)
        current_strike = self._short_instrument.strike_price.as_decimal()
        leaps_strike = self._leaps_instrument.strike_price.as_decimal() if self._leaps_instrument else spot

        roll_target = select_short_call_roll_target(
            candidates=candidates,
            spot=spot,
            prior_short_strike=current_strike,
            leaps_strike=leaps_strike,
            config=self._config,
        )

        if roll_target is None:
            self.log.warning("No eligible roll target for short call")
            return

        # Close current short call (BUY to close)
        close_order: MarketOrder = self.order_factory.market(
            instrument_id=self._short_instrument.id,
            order_side=OrderSide.BUY,
            quantity=self._short_instrument.make_qty(self._config.short_quantity),
            time_in_force=TimeInForce.GTC,
        )

        close_spec = LegSpec(
            instrument_id=str(self._short_instrument.id),
            side="BUY",
            quantity=self._config.short_quantity,
        )
        self._roll_leg_group = LegGroup(name="short_roll_close")
        self._roll_leg_group.add_leg(close_spec, str(close_order.client_order_id))
        self.submit_order(close_order)

        self._new_short_target = roll_target
        self._prior_short_strike = current_strike
        self._state = PMCCState.ROLLING_SHORT
        self.log.info(
            f"Short roll initiated: closing {self._short_instrument.id}, targeting {roll_target.instrument_id}",
        )

    def _complete_short_roll(self) -> None:
        """Submit the opening leg of the short call roll after the close leg fills."""
        if self._new_short_target is None:
            self.log.warning("No roll target set; returning to ACTIVE")
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            return

        new_inst = self.cache.instrument(InstrumentId.from_str(self._new_short_target.instrument_id))
        if new_inst is None:
            self.log.warning(f"Roll target instrument not found: {self._new_short_target.instrument_id}")
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            return

        # Open new short call (SELL to open)
        open_order: MarketOrder = self.order_factory.market(
            instrument_id=new_inst.id,
            order_side=OrderSide.SELL,
            quantity=new_inst.make_qty(self._config.short_quantity),
            time_in_force=TimeInForce.GTC,
        )
        open_spec = LegSpec(
            instrument_id=self._new_short_target.instrument_id,
            side="SELL",
            quantity=self._config.short_quantity,
        )
        self._roll_leg_group.add_leg(open_spec, str(open_order.client_order_id))
        self.submit_order(open_order)

        # Update tracking; if the open leg fills next it will be reconciled
        # into the same roll_leg_group, and is_complete will trigger again.
        # We stay in ROLLING_SHORT until both close and open are done.
        self._short_instrument = new_inst
        self._new_short_target = None

        # Check if already complete (unlikely but possible)
        if self._roll_leg_group.is_complete:
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            self.log.info("Short roll complete (both legs filled)", color=LogColor.GREEN)

    def _initiate_leaps_roll(self, spot: Decimal, bar: Bar) -> None:
        """Initiate a LEAPS roll: close current, then open new."""
        if self._leaps_instrument is None:
            return

        candidates = self._build_leaps_candidates(spot)
        roll_target = select_leaps_roll_target(candidates, spot, self._config)

        if roll_target is None:
            self.log.warning("No eligible roll target for LEAPS")
            return

        # Close current LEAPS (SELL to close)
        close_order: MarketOrder = self.order_factory.market(
            instrument_id=self._leaps_instrument.id,
            order_side=OrderSide.SELL,
            quantity=self._leaps_instrument.make_qty(self._config.leaps_quantity),
            time_in_force=TimeInForce.GTC,
        )
        close_spec = LegSpec(
            instrument_id=str(self._leaps_instrument.id),
            side="SELL",
            quantity=self._config.leaps_quantity,
        )
        self._roll_leg_group = LegGroup(name="leaps_roll_close")
        self._roll_leg_group.add_leg(close_spec, str(close_order.client_order_id))
        self.submit_order(close_order)

        self._new_leaps_target = roll_target
        self._state = PMCCState.ROLLING_LEAPS
        self.log.info(
            f"LEAPS roll initiated: closing {self._leaps_instrument.id}, targeting {roll_target.instrument_id}",
        )

    def _complete_leaps_roll(self) -> None:
        """Submit the opening leg of the LEAPS roll after the close leg fills."""
        if self._new_leaps_target is None:
            self.log.warning("No LEAPS roll target set; returning to ACTIVE")
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            return

        new_inst = self.cache.instrument(InstrumentId.from_str(self._new_leaps_target.instrument_id))
        if new_inst is None:
            self.log.warning(f"LEAPS roll target instrument not found: {self._new_leaps_target.instrument_id}")
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            return

        # Open new LEAPS (BUY to open)
        open_order: MarketOrder = self.order_factory.market(
            instrument_id=new_inst.id,
            order_side=OrderSide.BUY,
            quantity=new_inst.make_qty(self._config.leaps_quantity),
            time_in_force=TimeInForce.GTC,
        )
        open_spec = LegSpec(
            instrument_id=self._new_leaps_target.instrument_id,
            side="BUY",
            quantity=self._config.leaps_quantity,
        )
        self._roll_leg_group.add_leg(open_spec, str(open_order.client_order_id))
        self.submit_order(open_order)

        self._leaps_instrument = new_inst
        self._new_leaps_target = None

        if self._roll_leg_group.is_complete:
            self._state = PMCCState.ACTIVE
            self._roll_leg_group = None
            self.log.info("LEAPS roll complete (both legs filled)", color=LogColor.GREEN)

    # ── Snapshot / candidate builders ─────────────────────────────────────

    def _load_option_instruments(self) -> list[OptionContract]:
        """Load option instruments for the underlying from the cache."""
        instruments: list[OptionContract] = []
        underlying_symbol = self._instrument_id.symbol.value
        for inst in self.cache.instruments():
            if isinstance(inst, OptionContract) and inst.underlying == underlying_symbol:
                instruments.append(inst)
        return instruments

    def _build_leaps_candidates(self, spot: Decimal) -> list[OptionCandidate]:
        """Filter catalog options to LEAPS-eligible call candidates."""
        candidates: list[OptionCandidate] = []
        for inst in self._option_instruments:
            if inst.option_kind != OptionKind.CALL:
                continue
            dte = self._compute_dte(inst.expiration_ns)
            if dte < self._config.leaps_min_dte:
                continue
            if self._config.leaps_max_dte is not None and dte > self._config.leaps_max_dte:
                continue
            delta = self._estimate_delta(inst, spot)
            mid = self._get_option_mid(inst)
            oi = self._get_open_interest(inst)
            candidates.append(
                OptionCandidate(
                    instrument_id=str(inst.id),
                    right="C",
                    strike=inst.strike_price.as_decimal(),
                    dte=dte,
                    delta=delta,
                    mid=mid,
                    open_interest=oi,
                )
            )
        return candidates

    def _build_short_candidates(self, spot: Decimal) -> list[OptionCandidate]:
        """Filter catalog options to short-call-eligible near-term candidates."""
        candidates: list[OptionCandidate] = []
        for inst in self._option_instruments:
            if inst.option_kind != OptionKind.CALL:
                continue
            dte = self._compute_dte(inst.expiration_ns)
            if dte < self._config.short_min_dte:
                continue
            if self._config.short_max_dte is not None and dte > self._config.short_max_dte:
                continue
            delta = self._estimate_delta(inst, spot)
            mid = self._get_option_mid(inst)
            oi = self._get_open_interest(inst)
            candidates.append(
                OptionCandidate(
                    instrument_id=str(inst.id),
                    right="C",
                    strike=inst.strike_price.as_decimal(),
                    dte=dte,
                    delta=delta,
                    mid=mid,
                    open_interest=oi,
                )
            )
        return candidates

    def _build_short_snapshot(self, spot: Decimal) -> PositionSnapshot | None:
        """Build a :class:`PositionSnapshot` for the current short call position."""
        if self._short_instrument is None:
            return None

        inst = self._short_instrument
        dte = self._compute_dte(inst.expiration_ns)
        strike = inst.strike_price.as_decimal()

        # PnL fraction: (premium captured - cost to close) / premium captured
        # For a short call, max profit = premium received; current cost to close
        # is approximated from the delta and spot.
        if self._short_fill_price > 0:
            current_price = self._estimate_short_call_price(spot, strike, dte)
            pnl = (self._short_fill_price - current_price) / self._short_fill_price
            pnl = max(Decimal("0"), min(Decimal("1"), pnl))
        else:
            pnl = Decimal("0")

        return PositionSnapshot(
            symbol=self._config.underlying,
            right="C",
            strike=strike,
            spot=spot,
            dte=dte,
            pnl=pnl,
            itm=None,
        )

    def _build_leaps_info(self, spot: Decimal) -> dict | None:
        """Build a dict with LEAPS dte and delta for the roll decision."""
        if self._leaps_instrument is None:
            return None

        inst = self._leaps_instrument
        dte = self._compute_dte(inst.expiration_ns)
        delta = self._estimate_delta(inst, spot)

        return {"dte": dte, "delta": delta}

    # ── Utility helpers ──────────────────────────────────────────────────

    def _compute_dte(self, expiration_ns: int) -> int:
        """Compute days-to-expiry from a nanosecond timestamp."""
        expiry = unix_nanos_to_dt(expiration_ns)
        now = self.clock.utc_now()
        return max(0, (expiry.date() - now.date()).days)

    def _estimate_delta(self, inst: OptionContract, spot: Decimal) -> Decimal:
        """Estimate call delta via Black-Scholes approximation."""
        strike = inst.strike_price.as_decimal()
        dte = self._compute_dte(inst.expiration_ns)
        return approx_call_delta(strike, spot, dte)

    def _get_option_mid(self, inst: OptionContract) -> Decimal:
        """Get the mid price for an option instrument.

        Attempts to read from the cache (last bar); falls back to an intrinsic
        value approximation.
        """
        # Try cache for a recent bar
        bar_type_str = f"{inst.id}-1-HOUR-LAST-EXTERNAL"
        try:
            bt = BarType.from_str(bar_type_str)
            bar = self.cache.bar(bt)
            if bar is not None:
                return bar.close.as_decimal()
        except Exception:
            pass
        return Decimal("0")

    def _get_open_interest(self, inst: OptionContract) -> int:
        """Extract open interest from the instrument info dict, if present."""
        if inst.info is not None and isinstance(inst.info, dict):
            return int(inst.info.get("open_interest", 0))
        return 0

    def _estimate_short_call_price(
        self,
        spot: Decimal,
        strike: Decimal,
        dte: int,
    ) -> Decimal:
        """Estimate the current price of the short call for PnL tracking.

        Uses NautilusTrader's native Black-Scholes model via
        :func:`~trade_system_strategies.shared.option_pricing.bs_call_price`
        for accurate pricing.
        """
        return bs_call_price(spot, strike, dte)

    def _track_fill_prices(self, client_order_id: str, fill_price: Decimal) -> None:
        """Record fill prices for LEAPS and short legs based on the leg group mapping."""
        if self._leg_group is None:
            return
        idx = self._leg_group._order_to_leg.get(client_order_id)
        if idx is None:
            return
        leg = self._leg_group.legs[idx]
        if leg.spec.side == "BUY":
            self._leaps_fill_price = fill_price
        elif leg.spec.side == "SELL":
            self._short_fill_price = fill_price

    def _record_trade_stats(self) -> None:
        """Record the completed PMCC trade into the statistics accumulator."""
        if self._leg_group is not None:
            pnl = self._leg_group.net_cost
            self._stats.record(pnl, None)
        self.log.info(f"PMCC trade recorded: stats n={self._stats.count}")

    def _reset_position(self) -> None:
        """Reset all position tracking state back to flat."""
        self._leg_group = None
        self._roll_leg_group = None
        self._leaps_instrument = None
        self._short_instrument = None
        self._leaps_fill_price = Decimal("0")
        self._short_fill_price = Decimal("0")
        self._prior_short_strike = None
        self._new_short_target = None
        self._new_leaps_target = None
        self._state = PMCCState.FLAT
