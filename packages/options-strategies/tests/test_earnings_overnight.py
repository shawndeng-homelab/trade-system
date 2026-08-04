"""Verify earnings-overnight public API imports work end-to-end.

This file covers the config layer, the signal functions, and the
end-to-end strategy dispatch. All tests use fully synthetic data so no
API keys or parquet caches are required.
"""

from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from earnings_datasource import EarningsCalendar
from earnings_datasource import EarningsEvent
from earnings_datasource.providers.store import read_earnings
from earnings_datasource.providers.store import write_earnings
from options_strategies.earnings_overnight import EarningsOvernightConfig
from options_strategies.earnings_overnight import run_earnings_overnight
from options_strategies.earnings_overnight.config import EarningsOvernightConfig as ConfigDirect
from options_strategies.earnings_overnight.signals import earnings_event_dates
from options_strategies.earnings_overnight.signals import load_earnings_calendar
from options_strategies.earnings_overnight.signals import select_options_for_events
from options_strategies.earnings_overnight.signals import split_options_by_side
from options_strategies.earnings_overnight.strategy import run_earnings_overnight as run_direct
from pydantic import ValidationError


# ── Config tests ───────────────────────────────────────────────────────────


def test_earnings_config_defaults() -> None:
    """EarningsOvernightConfig can be instantiated with only required defaults."""
    config = EarningsOvernightConfig()
    assert config.symbol == "SPY"
    assert config.capital == 100_000.0
    assert config.quantity == 1
    assert config.multiplier == 100
    assert config.otm_target_pct == 0.02
    assert config.otm_tolerance_pct == 0.005
    assert config.reference_price == "high"
    assert config.min_oi == 100
    assert config.min_volume == 50
    assert config.max_entry_dte == 14
    assert config.cost_cap_usd == 1000.0
    assert config.call_weight == 0.5
    assert config.put_weight == 0.5


def test_earnings_config_custom() -> None:
    """EarningsOvernightConfig accepts custom strike and risk parameters."""
    config = EarningsOvernightConfig(
        symbol="QQQ",
        capital=50_000.0,
        otm_target_pct=0.03,
        otm_tolerance_pct=0.01,
        min_oi=200,
        min_volume=100,
        max_entry_dte=21,
        cost_cap_usd=500.0,
        reference_price="close",
    )
    assert config.symbol == "QQQ"
    assert config.capital == 50_000.0
    assert config.otm_target_pct == 0.03
    assert config.reference_price == "close"
    assert config.cost_cap_usd == 500.0


def test_earnings_config_frozen() -> None:
    """EarningsOvernightConfig is frozen (immutable)."""
    config = EarningsOvernightConfig()
    try:
        config.capital = 999  # type: ignore[misc]
    except Exception:
        pass
    else:
        msg = "Frozen config should reject attribute assignment"
        raise AssertionError(msg)


def test_earnings_config_weights_sum_to_one() -> None:
    """Default 0.5/0.5 sums to 1.0; 0.6/0.4 accepted; 0.7/0.7 rejected."""
    EarningsOvernightConfig()
    EarningsOvernightConfig(call_weight=0.6, put_weight=0.4)
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(call_weight=0.7, put_weight=0.7)


def test_earnings_config_dte_ordering() -> None:
    """min_entry_dte must be strictly less than max_entry_dte."""
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(min_entry_dte=14, max_entry_dte=14)
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(min_entry_dte=20, max_entry_dte=14)


def test_earnings_config_reference_price_validation() -> None:
    """reference_price must be "high" or "close"."""
    EarningsOvernightConfig(reference_price="high")
    EarningsOvernightConfig(reference_price="close")
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(reference_price="low")  # type: ignore[arg-type]


def test_earnings_config_otm_tolerance_ordering() -> None:
    """otm_tolerance_pct must be strictly less than otm_target_pct."""
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(otm_target_pct=0.02, otm_tolerance_pct=0.02)
    with pytest.raises(ValidationError):
        EarningsOvernightConfig(otm_target_pct=0.02, otm_tolerance_pct=0.05)


def test_api_aliases_match() -> None:
    """Top-level re-exports point to the same objects as the submodules."""
    assert EarningsOvernightConfig is ConfigDirect
    assert run_earnings_overnight is run_direct


# ── Shared synthetic data helpers ──────────────────────────────────────────


def _synthetic_stock(
    symbol: str = "TEST.US",
    start: str = "2024-01-01",
    n_days: int = 60,
    base: float = 100.0,
) -> pd.DataFrame:
    """Build a minimal stock OHLCV DataFrame for signal tests.

    Default OHLCV = base (no intraday range) so the reference price is
    exactly ``base`` for predictable strike-band math.
    """
    dates = pd.date_range(start, periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "underlying_symbol": symbol,
            "quote_date": dates,
            "open": base,
            "high": base,
            "low": base,
            "close": base,
            "volume": 1_000_000,
        }
    )


def _synthetic_options_chain(
    symbol: str,
    quote_date: pd.Timestamp,
    rows: list[dict],
) -> pd.DataFrame:
    """Build a single-day options chain DataFrame.

    Each row in ``rows`` is a dict with keys: opt_type, strike, oi, vol,
    ask, bid, expiration (date or pd.Timestamp), delta.
    """
    records = []
    for r in rows:
        records.append(
            {
                "underlying_symbol": symbol,
                "option_type": r["opt_type"],
                "strike": float(r["strike"]),
                "expiration": pd.Timestamp(r["expiration"]),
                "quote_date": pd.Timestamp(quote_date),
                "bid": float(r.get("bid", max(r["ask"] - 0.05, 0.01))),
                "ask": float(r["ask"]),
                "delta": float(r.get("delta", 0.5)),
                "open_interest": int(r.get("oi", 100)),
                "volume": int(r.get("vol", 50)),
            }
        )
    return pd.DataFrame.from_records(records)


def _seed_earnings_cache(
    tmp_path: Path,
    code: str,
    report_dates: list[pd.Timestamp],
) -> None:
    """Write an earnings parquet cache for *code* with the given report dates."""
    events = [
        EarningsEvent(
            code=code,
            report_date=datetime(d.year, d.month, d.day, tzinfo=UTC),
            session="amc",
        )
        for d in report_dates
    ]
    df = EarningsCalendar(events=events, source="eodhd").to_dataframe()
    write_earnings(code, df, root=tmp_path)


# ── load_earnings_calendar tests ──────────────────────────────────────────


def test_load_earnings_calendar_filters_by_as_of(tmp_path: Path) -> None:
    """Future events (report_date > as_of_date) are filtered out."""
    code = "TEST.US"
    _seed_earnings_cache(
        tmp_path,
        code,
        [pd.Timestamp("2024-02-01"), pd.Timestamp("2025-01-01")],
    )
    cal = load_earnings_calendar([code], as_of_date=date(2024, 6, 1), root=tmp_path)
    assert code in cal
    assert len(cal[code]) == 1
    assert cal[code][0] == pd.Timestamp("2024-02-01")


def test_load_earnings_calendar_missing_cache(tmp_path: Path) -> None:
    """Missing cache file → symbol omitted from result, no exception."""
    cal = load_earnings_calendar(["NOPE"], root=tmp_path)
    assert cal == {}


def test_load_earnings_calendar_dedupes(tmp_path: Path) -> None:
    """Duplicate report_dates in the cache collapse to one entry."""
    code = "TEST.US"
    _seed_earnings_cache(tmp_path, code, [pd.Timestamp("2024-02-01")])
    df = read_earnings(code, root=tmp_path)
    assert df is not None
    duplicated = pd.concat([df, df.iloc[0:1]], ignore_index=True)
    write_earnings(code, duplicated, root=tmp_path)

    cal = load_earnings_calendar([code], root=tmp_path)
    assert len(cal[code]) == 1


# ── earnings_event_dates tests ─────────────────────────────────────────────


def test_earnings_event_dates_weekday(tmp_path: Path) -> None:
    """Weekday report: entry=T-1, exit=T."""
    _seed_earnings_cache(tmp_path, "TEST.US", [pd.Timestamp("2024-02-05")])  # Monday
    stock = _synthetic_stock(start="2024-01-01", n_days=30)
    cal = load_earnings_calendar(["TEST"], root=tmp_path)
    events = earnings_event_dates(stock, cal, EarningsOvernightConfig())
    assert len(events) == 1
    assert events.iloc[0]["report_date"] == pd.Timestamp("2024-02-05")
    assert events.iloc[0]["entry_date"] < pd.Timestamp("2024-02-05")
    assert events.iloc[0]["exit_date"] >= pd.Timestamp("2024-02-05")


def test_earnings_event_dates_saturday(tmp_path: Path) -> None:
    """Saturday report: entry=Friday, exit=Monday."""
    _seed_earnings_cache(tmp_path, "TEST.US", [pd.Timestamp("2024-02-03")])  # Saturday
    stock = _synthetic_stock(start="2024-01-01", n_days=30)
    cal = load_earnings_calendar(["TEST"], root=tmp_path)
    events = earnings_event_dates(stock, cal, EarningsOvernightConfig())
    assert len(events) == 1
    row = events.iloc[0]
    assert row["entry_date"] == pd.Timestamp("2024-02-02")  # Friday
    assert row["exit_date"] == pd.Timestamp("2024-02-05")  # Monday


def test_earnings_event_dates_outside_range(tmp_path: Path) -> None:
    """Earnings outside the stock data range → row dropped."""
    _seed_earnings_cache(tmp_path, "TEST.US", [pd.Timestamp("2030-01-01")])  # far future
    stock = _synthetic_stock(start="2024-01-01", n_days=30)
    cal = load_earnings_calendar(["TEST"], root=tmp_path)
    events = earnings_event_dates(stock, cal, EarningsOvernightConfig())
    assert events.empty


def test_earnings_event_dates_no_overnight(tmp_path: Path) -> None:
    """Defensive: entry_date NaT (no prior trading day) → row dropped."""
    _seed_earnings_cache(tmp_path, "TEST.US", [pd.Timestamp("2024-01-02")])  # first day
    stock = _synthetic_stock(start="2024-01-02", n_days=1)
    cal = load_earnings_calendar(["TEST"], root=tmp_path)
    events = earnings_event_dates(stock, cal, EarningsOvernightConfig())
    assert events.empty


# ── select_options_for_events tests ────────────────────────────────────────


def _two_event_setup(base: float = 100.0):
    """Helper: returns (options_df, stock_df, events) for two synthetic events.

    Reference price = 100 (so call_target=102, put_target=98 with
    default 0.005 tolerance → bands [101.5, 102.5] and [97.5, 98.5]).

    Event 1 (entry 2024-02-02): call wins (OI*vol 40k > 22.5k put).
    Event 2 (entry 2024-02-09): put wins (OI*vol 90k > 10k call).
    """
    entry1 = pd.Timestamp("2024-02-02")  # Friday
    entry2 = pd.Timestamp("2024-02-09")  # Friday
    stock = pd.DataFrame(
        {
            "underlying_symbol": ["TEST.US"] * 30,
            "quote_date": pd.date_range("2024-01-15", periods=30, freq="B"),
            "open": base,
            "high": base,
            "low": base,
            "close": base,
            "volume": 1_000_000,
        }
    )
    exp = pd.Timestamp("2024-02-16")
    chain1 = _synthetic_options_chain(
        "TEST.US",
        entry1,
        rows=[
            # Top call: OI*vol = 200*200 = 40,000
            {"opt_type": "c", "strike": 102, "ask": 1.5, "oi": 200, "vol": 200, "expiration": exp},
            # Worse call: OI*vol = 100*100 = 10,000
            {"opt_type": "c", "strike": 101.5, "ask": 2.0, "oi": 100, "vol": 100, "expiration": exp},
            # Top put: OI*vol = 150*150 = 22,500 (call still wins)
            {"opt_type": "p", "strike": 98, "ask": 1.8, "oi": 150, "vol": 150, "expiration": exp},
        ],
    )
    chain2 = _synthetic_options_chain(
        "TEST.US",
        entry2,
        rows=[
            # Put side wins (OI*vol = 300*300 = 90,000)
            {"opt_type": "p", "strike": 98, "ask": 2.5, "oi": 300, "vol": 300, "expiration": exp},
            # Call side weaker
            {"opt_type": "c", "strike": 102, "ask": 2.0, "oi": 100, "vol": 100, "expiration": exp},
        ],
    )
    options_df = pd.concat([chain1, chain2], ignore_index=True)
    events = pd.DataFrame(
        {
            "underlying_symbol": ["TEST.US", "TEST.US"],
            "report_date": [pd.Timestamp("2024-02-05"), pd.Timestamp("2024-02-12")],
            "entry_date": [entry1, entry2],
            "exit_date": [pd.Timestamp("2024-02-05"), pd.Timestamp("2024-02-12")],
        }
    )
    return options_df, stock, events


def test_select_options_picks_highest_oi_vol() -> None:
    """Call wins event 1 (40k vs 22.5k); put wins event 2 (90k vs 10k)."""
    options_df, stock, events = _two_event_setup()
    config = EarningsOvernightConfig()
    selected = select_options_for_events(options_df, stock, events, config)
    assert len(selected) == 2
    first = selected[selected["quote_date"] == pd.Timestamp("2024-02-02")].iloc[0]
    assert first["option_type"] == "c"
    second = selected[selected["quote_date"] == pd.Timestamp("2024-02-09")].iloc[0]
    assert second["option_type"] == "p"


def test_select_options_skips_when_no_candidates_meet_thresholds() -> None:
    """All candidates fail OI/Volume thresholds → event dropped."""
    options_df, stock, events = _two_event_setup()
    config = EarningsOvernightConfig(min_oi=10_000, min_volume=10_000)
    selected = select_options_for_events(options_df, stock, events, config)
    assert selected.empty


def test_select_options_skips_when_cost_exceeds_cap() -> None:
    """Winner's cost > cost_cap → event dropped (no fallback to lower-score side).

    Patches the first chain's call ask to 20 (cost = 20 * 100 * 1 = 2000
    > 1000 cap). The 102 call is the winner (OI*vol 40k > 22.5k put) but
    busts the cap; per the plan's strict semantics, the event is dropped
    entirely (no entry, no quantity rescaling, no fallback to the put).
    """
    options_df, stock, events = _two_event_setup()
    options_df.loc[
        (options_df["quote_date"] == pd.Timestamp("2024-02-02"))
        & (options_df["option_type"] == "c")
        & (options_df["strike"] == 102),
        "ask",
    ] = 20.0
    selected = select_options_for_events(options_df, stock, events, EarningsOvernightConfig())
    first_chain = selected[selected["quote_date"] == pd.Timestamp("2024-02-02")]
    # Event 1 dropped; event 2 still has the put within cap and survives.
    assert first_chain.empty
    assert len(selected) == 1
    assert selected.iloc[0]["quote_date"] == pd.Timestamp("2024-02-09")


def test_select_options_respects_dte_cap() -> None:
    """Options with DTE > max_entry_dte are filtered out.

    Default expiration is 2024-02-16; entries are 2024-02-02 (DTE 14) and
    2024-02-09 (DTE 7). With max_entry_dte=7: event 1's options all fail,
    event 2's options pass.
    """
    options_df, stock, events = _two_event_setup()
    config = EarningsOvernightConfig(max_entry_dte=7)
    selected = select_options_for_events(options_df, stock, events, config)
    # Only event 2 survives
    assert len(selected) == 1
    assert selected.iloc[0]["quote_date"] == pd.Timestamp("2024-02-09")


def test_select_options_respects_strike_tolerance() -> None:
    """Strikes outside ±tolerance are filtered out.

    With tight tolerance (0.001): call band [101.9, 102.1] — only 102
    fits; 101.5 is out. put band [97.9, 98.1] — only 98 fits.
    """
    options_df, stock, events = _two_event_setup()
    config = EarningsOvernightConfig(otm_tolerance_pct=0.001)
    selected = select_options_for_events(options_df, stock, events, config)
    # Event 1: 102 call (40k) > 98 put (22.5k) → call
    # Event 2: 102 call (10k) < 98 put (90k) → put
    assert len(selected) == 2
    first = selected[selected["quote_date"] == pd.Timestamp("2024-02-02")].iloc[0]
    assert first["option_type"] == "c"
    second = selected[selected["quote_date"] == pd.Timestamp("2024-02-09")].iloc[0]
    assert second["option_type"] == "p"


def test_split_options_by_side() -> None:
    """split_options_by_side returns (calls, puts) split correctly."""
    options_df = pd.DataFrame(
        {
            "underlying_symbol": ["X", "X"],
            "option_type": ["c", "p"],
            "strike": [100.0, 100.0],
            "quote_date": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-02")],
        }
    )
    calls, puts = split_options_by_side(options_df)
    assert len(calls) == 1
    assert calls.iloc[0]["option_type"] == "c"
    assert len(puts) == 1
    assert puts.iloc[0]["option_type"] == "p"


def test_split_options_by_side_empty() -> None:
    """Empty options_df → both sides empty."""
    calls, puts = split_options_by_side(pd.DataFrame(columns=["option_type"]))
    assert calls.empty
    assert puts.empty


def test_select_options_reference_price_close() -> None:
    """reference_price='close' uses close for the target strike."""
    options_df, stock, events = _two_event_setup()
    config = EarningsOvernightConfig(reference_price="close")
    selected = select_options_for_events(options_df, stock, events, config)
    # close=100 → same targets as the high-based test, so same winners.
    first = selected[selected["quote_date"] == pd.Timestamp("2024-02-02")].iloc[0]
    assert first["option_type"] == "c"


# ── End-to-end strategy tests ─────────────────────────────────────────────


def _full_options_for_two_events() -> pd.DataFrame:
    """Build a comprehensive options_df covering entry + exit dates for both events.

    Each event uses its own expiration so the pre-filtered legs don't
    conflict on (symbol, option_type, strike, expiration). Both
    expirations are within ``max_entry_dte=14`` of the entry day, so
    optopsy's entry filter accepts them. The data extends to each
    event's expiration so optopsy's ``exit_dte=0`` logic can find an
    exit row.

    Event 1: entry 2024-02-02 (Fri), exit 2024-02-05 (Mon). Expiration 2024-02-09.
    Event 2: entry 2024-02-09 (Fri), exit 2024-02-12 (Tue). Expiration 2024-02-16.
    """
    days = pd.date_range("2024-02-01", "2024-02-16", freq="B")
    rows = []
    for d in days:
        # Event 1 options (expiration 2024-02-09)
        exp1 = pd.Timestamp("2024-02-09")
        for ot, strike, ask, oi, vol, delta in [
            ("c", 102.0, 1.5, 200, 200, 0.5),  # top call event 1
            ("p", 98.0, 1.8, 150, 150, 0.5),  # top put event 1 (positive delta)
        ]:
            # Exit day (Mon 2024-02-05): bad earnings → call drops, put rises
            if d == pd.Timestamp("2024-02-05"):
                ask = 0.5 if ot == "c" else 3.5
            # Expiration day (Fri 2024-02-09): value ≈ 0
            if d == exp1:
                ask = 0.01
            rows.append(
                {
                    "underlying_symbol": "TEST.US",
                    "option_type": ot,
                    "strike": strike,
                    "expiration": exp1,
                    "quote_date": d,
                    "bid": max(ask - 0.05, 0.01),
                    "ask": ask,
                    "delta": delta,
                    "open_interest": oi,
                    "volume": vol,
                }
            )
        # Event 2 options (expiration 2024-02-16)
        exp2 = pd.Timestamp("2024-02-16")
        for ot, strike, ask, oi, vol, delta in [
            ("c", 102.0, 2.0, 100, 100, 0.5),  # weak call event 2
            ("p", 98.0, 2.5, 300, 300, 0.5),  # top put event 2
        ]:
            if d == pd.Timestamp("2024-02-12"):
                ask = 0.3 if ot == "c" else 4.5
            if d == exp2:
                ask = 0.01
            rows.append(
                {
                    "underlying_symbol": "TEST.US",
                    "option_type": ot,
                    "strike": strike,
                    "expiration": exp2,
                    "quote_date": d,
                    "bid": max(ask - 0.05, 0.01),
                    "ask": ask,
                    "delta": delta,
                    "open_interest": oi,
                    "volume": vol,
                }
            )
    return pd.DataFrame(rows)


def test_run_earnings_overnight_no_events_survives() -> None:
    """All events filtered out → ValueError before dispatch."""
    options_df, stock, _events = _two_event_setup()
    # Force the cost cap to be so low that no candidate fits
    config = EarningsOvernightConfig(cost_cap_usd=0.001)
    # Empty calendar → no events to process
    with pytest.raises(ValueError, match="No earnings events survived"):
        run_earnings_overnight(options_df, stock, {}, config)


def test_run_earnings_overnight_smoke() -> None:
    """One event passes selection → simulate produces a non-empty trade log."""
    options_df = _full_options_for_two_events()
    # Stock: flat $100, covers the relevant dates
    stock = pd.DataFrame(
        {
            "underlying_symbol": ["TEST.US"] * 14,
            "quote_date": pd.date_range("2024-02-01", "2024-02-20", freq="B"),
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
    )
    # Synthetic earnings calendar (both events)
    cal = {
        "TEST.US": [pd.Timestamp("2024-02-05"), pd.Timestamp("2024-02-12")],
    }
    config = EarningsOvernightConfig()
    result = run_earnings_overnight(options_df, stock, cal, config)
    # Two events fire, each picks a side → two trades
    assert len(result.trade_log) >= 1
    assert "earnings_call" in result.leg_results or "earnings_put" in result.leg_results


def test_run_earnings_overnight_picks_puts_when_put_oi_higher() -> None:
    """When put OI×Vol > call OI×Vol across both events, the put leg fires."""
    options_df = _full_options_for_two_events()
    stock = pd.DataFrame(
        {
            "underlying_symbol": ["TEST.US"] * 14,
            "quote_date": pd.date_range("2024-02-01", "2024-02-20", freq="B"),
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
    )
    cal = {
        "TEST.US": [pd.Timestamp("2024-02-05"), pd.Timestamp("2024-02-12")],
    }
    config = EarningsOvernightConfig()
    result = run_earnings_overnight(options_df, stock, cal, config)
    # The put leg must exist and have at least one trade (event 2's put wins).
    # The call leg may also exist (event 1's call wins); we don't assert on it.
    assert "earnings_put" in result.leg_results
    put_trades = result.leg_results["earnings_put"].trade_log
    assert len(put_trades) >= 1
