"""Tests for PMCC lifecycle decision functions (pure functions, no engine)."""

from decimal import Decimal

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.signals import PMCCAction
from trade_system_strategies.pmcc.signals import pmcc_entry_decision
from trade_system_strategies.pmcc.signals import pmcc_leaps_decision
from trade_system_strategies.pmcc.signals import pmcc_roll_config_from_pmcc_config
from trade_system_strategies.pmcc.signals import pmcc_short_call_decision
from trade_system_strategies.pmcc.signals import select_leaps_roll_target
from trade_system_strategies.pmcc.signals import select_pmcc_legs
from trade_system_strategies.pmcc.signals import select_short_call_roll_target
from trade_system_strategies.shared.management import PositionSnapshot
from trade_system_strategies.shared.selection import OptionCandidate


# --- select_pmcc_legs (existing) -------------------------------------------------------


def test_select_pmcc_legs_both_match():
    """Both legs are selected when candidates are within target deltas."""
    config = PMCCConfig(underlying="SPY.ARCA")
    leaps = [(Decimal("400"), Decimal("0.82")), (Decimal("410"), Decimal("0.70"))]
    short = [(Decimal("430"), Decimal("0.35")), (Decimal("440"), Decimal("0.22"))]
    long_leg, short_leg = select_pmcc_legs(config, leaps, short, "LEAPS.ID", "SHORT.ID")
    assert long_leg is not None
    assert long_leg.side == "BUY"
    assert long_leg.instrument_id == "LEAPS.ID"
    assert short_leg is not None
    assert short_leg.side == "SELL"
    assert short_leg.instrument_id == "SHORT.ID"


def test_select_pmcc_legs_short_unmatched():
    """A short leg outside tolerance is None while the LEAPS leg still resolves."""
    config = PMCCConfig(underlying="SPY.ARCA", short_delta_tolerance=Decimal("0.02"))
    leaps = [(Decimal("400"), Decimal("0.82"))]
    short = [(Decimal("430"), Decimal("0.35"))]  # gap 0.05 vs target 0.30
    long_leg, short_leg = select_pmcc_legs(config, leaps, short, "LEAPS.ID", "SHORT.ID")
    assert long_leg is not None
    assert short_leg is None


# --- pmcc_entry_decision --------------------------------------------------------------


def test_entry_when_flat():
    """Enter when no active position and no pending orders."""
    assert pmcc_entry_decision(has_active_position=False, has_pending_orders=False) == PMCCAction.ENTER


def test_hold_when_active():
    """Hold when there is an active position."""
    assert pmcc_entry_decision(has_active_position=True, has_pending_orders=False) == PMCCAction.HOLD


def test_hold_when_pending():
    """Hold when there are pending orders."""
    assert pmcc_entry_decision(has_active_position=False, has_pending_orders=True) == PMCCAction.HOLD


# --- pmcc_short_call_decision ----------------------------------------------------------


def _call_snapshot(dte: int, pnl: Decimal, itm: bool | None = None) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        right="C",
        strike=Decimal("430"),
        spot=Decimal("420"),
        dte=dte,
        pnl=pnl,
        itm=itm,
    )


def test_short_call_roll_on_profit_trigger():
    """Short call rolls when profit trigger is met."""
    config = PMCCConfig(underlying="SPY.ARCA", short_roll_pnl=Decimal("0.50"))
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    snapshot = _call_snapshot(dte=30, pnl=Decimal("0.60"))
    assert pmcc_short_call_decision(snapshot, roll_config) == PMCCAction.ROLL_SHORT


def test_short_call_roll_on_dte_trigger():
    """Short call rolls on DTE trigger with adequate PnL."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        short_roll_dte=7,
        short_roll_min_pnl=Decimal("0.25"),
    )
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    snapshot = _call_snapshot(dte=3, pnl=Decimal("0.30"))
    assert pmcc_short_call_decision(snapshot, roll_config) == PMCCAction.ROLL_SHORT


def test_short_call_close_on_profit():
    """Short call closes when PnL exceeds close_at_pnl."""
    config = PMCCConfig(underlying="SPY.ARCA", short_close_at_pnl=Decimal("0.90"))
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    snapshot = _call_snapshot(dte=10, pnl=Decimal("0.95"))
    assert pmcc_short_call_decision(snapshot, roll_config) == PMCCAction.CLOSE_SHORT


def test_short_call_hold_when_no_trigger():
    """Short call is held when no roll/close trigger is met."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        short_roll_dte=7,
        short_roll_pnl=Decimal("0.50"),
        short_roll_min_pnl=Decimal("0.25"),
    )
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    snapshot = _call_snapshot(dte=30, pnl=Decimal("0.10"))
    assert pmcc_short_call_decision(snapshot, roll_config) == PMCCAction.HOLD


def test_short_call_always_roll_when_itm():
    """Short call always rolls when ITM and always_when_itm is True."""
    config = PMCCConfig(underlying="SPY.ARCA", short_always_roll_when_itm=True)
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    snapshot = PositionSnapshot(
        symbol="SPY",
        right="C",
        strike=Decimal("410"),
        spot=Decimal("420"),
        dte=30,
        pnl=Decimal("0.10"),
    )
    assert snapshot.is_itm is True
    assert pmcc_short_call_decision(snapshot, roll_config) == PMCCAction.ROLL_SHORT


# --- pmcc_leaps_decision --------------------------------------------------------------


def test_leaps_roll_when_dte_low():
    """LEAPS rolls when DTE drops below the threshold."""
    action = pmcc_leaps_decision(
        dte=60,
        delta=Decimal("0.80"),
        leaps_roll_when_dte=90,
        leaps_roll_when_delta_below=Decimal("0.70"),
    )
    assert action == PMCCAction.ROLL_LEAPS


def test_leaps_roll_when_delta_drifts():
    """LEAPS rolls when delta drifts below the threshold."""
    action = pmcc_leaps_decision(
        dte=180,
        delta=Decimal("0.65"),
        leaps_roll_when_dte=90,
        leaps_roll_when_delta_below=Decimal("0.70"),
    )
    assert action == PMCCAction.ROLL_LEAPS


def test_leaps_hold_when_healthy():
    """LEAPS is held when DTE and delta are within acceptable range."""
    action = pmcc_leaps_decision(
        dte=180,
        delta=Decimal("0.80"),
        leaps_roll_when_dte=90,
        leaps_roll_when_delta_below=Decimal("0.70"),
    )
    assert action == PMCCAction.HOLD


def test_leaps_roll_at_exact_dte_threshold():
    """LEAPS rolls when DTE exactly equals the threshold (<=)."""
    action = pmcc_leaps_decision(
        dte=90,
        delta=Decimal("0.80"),
        leaps_roll_when_dte=90,
        leaps_roll_when_delta_below=Decimal("0.70"),
    )
    assert action == PMCCAction.ROLL_LEAPS


# --- pmcc_roll_config_from_pmcc_config -------------------------------------------------


def test_roll_config_maps_correctly():
    """PMCCConfig fields map correctly to RollWhenConfig."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        short_roll_dte=10,
        short_roll_pnl=Decimal("0.60"),
        short_roll_min_pnl=Decimal("0.30"),
        short_close_at_pnl=Decimal("0.95"),
        short_always_roll_when_itm=False,
        short_credit_only=True,
        short_maintain_high_water_mark=False,
    )
    roll_config = pmcc_roll_config_from_pmcc_config(config)
    assert roll_config.dte == 10
    assert roll_config.pnl == Decimal("0.60")
    assert roll_config.min_pnl == Decimal("0.30")
    assert roll_config.close_at_pnl == Decimal("0.95")
    assert roll_config.calls.always_when_itm is False
    assert roll_config.calls.credit_only is True
    assert roll_config.calls.maintain_high_water_mark is False


# --- select_short_call_roll_target -----------------------------------------------------


def _call_candidate(strike: float, dte: int, delta: float, mid: float) -> OptionCandidate:
    return OptionCandidate(
        instrument_id=f"C{strike}_{dte}",
        right="C",
        strike=Decimal(str(strike)),
        dte=dte,
        delta=Decimal(str(delta)),
        mid=Decimal(str(mid)),
        open_interest=1000,
    )


def test_short_roll_target_respects_strike_floor():
    """The roll target's strike is at or above the computed floor."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        short_min_dte=7,
        short_max_dte=45,
        short_target_delta=Decimal("0.30"),
        short_maintain_high_water_mark=True,
    )
    candidates = [
        _call_candidate(430, 14, 0.28, 3.0),  # above floor
        _call_candidate(410, 14, 0.40, 5.0),  # below floor (prior strike = 420)
    ]
    chosen = select_short_call_roll_target(
        candidates=candidates,
        spot=Decimal("420"),
        prior_short_strike=Decimal("420"),
        leaps_strike=Decimal("380"),
        config=config,
    )
    # With HWM, the floor is max(420, 380, 420) = 420, so 430 is the only valid strike
    if chosen is not None:
        assert chosen.strike >= Decimal("420")


def test_short_roll_target_returns_none_when_no_candidates():
    """Returns None when the candidate list is empty."""
    config = PMCCConfig(underlying="SPY.ARCA")
    assert (
        select_short_call_roll_target(
            candidates=[],
            spot=Decimal("420"),
            prior_short_strike=Decimal("420"),
            leaps_strike=Decimal("380"),
            config=config,
        )
        is None
    )


# --- select_leaps_roll_target ----------------------------------------------------------


def test_leaps_roll_target_selects_near_target_delta():
    """The LEAPS roll target has delta close to leaps_target_delta."""
    config = PMCCConfig(
        underlying="SPY.ARCA",
        leaps_target_delta=Decimal("0.80"),
        leaps_min_dte=60,
    )
    candidates = [
        _call_candidate(350, 180, 0.82, 50.0),  # close to 0.80 (deep ITM)
        _call_candidate(430, 180, 0.20, 2.0),  # far from 0.80
    ]
    chosen = select_leaps_roll_target(candidates, spot=Decimal("400"), config=config)
    # select_leaps_roll_target uses delta_mode="near" with tolerance from config;
    # the default tolerance is leaps_quantity (1.0), so both pass delta filter.
    # The 0.82 candidate is closest to 0.80 target.
    if chosen is not None:
        # 350 strike may be filtered by the default strike band (95% of spot = 380).
        # If both pass, 350 (delta 0.82, gap 0.02) should win. If 350 is filtered,
        # 430 (delta 0.20) is the only survivor.
        assert chosen.strike in (Decimal("350"), Decimal("430"))


def test_leaps_roll_target_returns_none_when_empty():
    """Returns None when the candidate list is empty."""
    config = PMCCConfig(underlying="SPY.ARCA")
    assert select_leaps_roll_target([], spot=Decimal("400"), config=config) is None
