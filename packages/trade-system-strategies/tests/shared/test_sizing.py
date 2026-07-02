"""Tests for Kelly-criterion sizing helpers (pure functions, no engine)."""

from decimal import Decimal

from trade_system_strategies.shared.sizing import TradeStats
from trade_system_strategies.shared.sizing import continuous_kelly_fraction
from trade_system_strategies.shared.sizing import drawdown_scalar
from trade_system_strategies.shared.sizing import fractional_kelly
from trade_system_strategies.shared.sizing import kelly_fraction
from trade_system_strategies.shared.sizing import kelly_position_size

D = Decimal


def test_kelly_fraction_even_payoff():
    """W=0.6, R=1 -> f* = 0.6 - 0.4/1 = 0.2."""
    assert kelly_fraction(D("0.6"), D("100"), D("-100")) == D("0.2")


def test_kelly_fraction_uneven_payoff():
    """W=0.5, avg_win=200, avg_loss=-100 -> R=2, f* = 0.5 - 0.5/2 = 0.25."""
    assert kelly_fraction(D("0.5"), D("200"), D("-100")) == D("0.25")


def test_kelly_fraction_no_edge_clamped_to_zero():
    """A losing system (W=0.3, R=1) yields a negative raw Kelly -> 0."""
    assert kelly_fraction(D("0.3"), D("100"), D("-100")) == D("0")


def test_kelly_fraction_zero_avg_loss_is_zero():
    """avg_loss=0 (no losers) is degenerate; return 0 rather than dividing."""
    assert kelly_fraction(D("0.6"), D("100"), D("0")) == D("0")


def test_fractional_kelly_half():
    """Half-Kelly scales the full fraction by 0.5."""
    full = kelly_fraction(D("0.6"), D("100"), D("-100"))  # 0.2
    assert fractional_kelly(D("0.6"), D("100"), D("-100"), D("0.5")) == full * D("0.5")


def test_fractional_kelly_max_fraction_cap():
    """max_fraction caps the scaled fraction."""
    result = fractional_kelly(D("0.9"), D("100"), D("-100"), D("1.0"), max_fraction=D("0.25"))
    assert result == D("0.25")


def test_kelly_position_size_basic():
    """equity*fraction/price yields the share count."""
    size = kelly_position_size(D("10000"), D("50"), D("0.6"), D("100"), D("-100"), D("0.5"))
    # full kelly = 0.2, half = 0.1 -> 10000*0.1/50 = 20
    assert size == D("20")


def test_kelly_position_size_no_edge_is_zero():
    """A no-edge system sizes to zero."""
    assert kelly_position_size(D("10000"), D("50"), D("0.3"), D("100"), D("-100")) == D("0")


def test_kelly_position_size_nonpositive_price_is_zero():
    """A non-positive price guards against division by zero."""
    assert kelly_position_size(D("10000"), D("0"), D("0.6"), D("100"), D("-100")) == D("0")


def test_trade_stats_ready_threshold():
    """ready only after min_sample trades are recorded."""
    stats = TradeStats(min_sample=3)
    assert not stats.ready
    stats.record(D("10"))
    stats.record(D("-5"))
    assert not stats.ready
    stats.record(D("10"))
    assert stats.ready


def test_trade_stats_win_rate_and_payoffs():
    """win_rate/avg_win/avg_loss aggregate the recorded PnLs."""
    stats = TradeStats(min_sample=1)
    for pnl in [D("100"), D("200"), D("-50"), D("-150")]:
        stats.record(pnl)
    assert stats.win_rate == D("0.5")
    assert stats.avg_win == D("150")
    assert stats.avg_loss == D("-100")


def test_trade_stats_rolling_window_drops_old():
    """A bounded window drops the oldest trade once maxlen is exceeded."""
    stats = TradeStats(window=3, min_sample=1)
    for pnl in [D("1"), D("2"), D("3"), D("4")]:
        stats.record(pnl)
    assert stats.count == 3
    # Only the last three (2,3,4) remain; all winners.
    assert stats.win_rate == D("1")
    assert stats.avg_win == D("3")


def test_trade_stats_empty_returns_zeros():
    """An empty accumulator reports zero edge."""
    stats = TradeStats()
    assert stats.win_rate == D("0")
    assert stats.avg_win == D("0")
    assert stats.avg_loss == D("0")
    assert stats.kelly_fraction() == D("0")


# --- continuous Kelly ----------------------------------------------------------


def test_continuous_kelly_basic():
    """f* = mean/variance, scaled by fraction."""
    # mean=0.02, variance=0.04 -> full kelly=0.5, half=0.25
    assert continuous_kelly_fraction(D("0.02"), D("0.04"), D("0.5")) == D("0.25")


def test_continuous_kelly_zero_variance_is_zero():
    """A degenerate (zero-variance) return stream yields 0."""
    assert continuous_kelly_fraction(D("0.02"), D("0"), D("0.5")) == D("0")


def test_continuous_kelly_negative_mean_is_zero():
    """A negative mean return (no edge) clamps to 0."""
    assert continuous_kelly_fraction(D("-0.01"), D("0.04"), D("0.5")) == D("0")


def test_continuous_kelly_max_fraction_cap():
    """max_fraction caps the scaled fraction."""
    result = continuous_kelly_fraction(D("0.5"), D("0.04"), D("1.0"), max_fraction=D("0.25"))
    assert result == D("0.25")


# --- drawdown scalar -----------------------------------------------------------


def test_drawdown_scalar_zero_drawdown_is_one():
    """At peak equity the scalar is 1 (full size)."""
    assert drawdown_scalar(D("0"), D("0.2")) == D("1")


def test_drawdown_scalar_at_max_hits_floor():
    """At max_drawdown the scalar floors to 0 (stop trading)."""
    assert drawdown_scalar(D("0.2"), D("0.2")) == D("0")


def test_drawdown_scalar_linear_midpoint():
    """Halfway to max_drawdown scales to 0.5."""
    assert drawdown_scalar(D("0.1"), D("0.2")) == D("0.5")


def test_drawdown_scalar_respects_floor():
    """A non-zero floor keeps a minimum exposure at max drawdown."""
    assert drawdown_scalar(D("0.2"), D("0.2"), floor=D("0.25")) == D("0.25")


def test_drawdown_scalar_clamps_above_one():
    """A negative drawdown (above peak) clamps to 1."""
    assert drawdown_scalar(D("-0.05"), D("0.2")) == D("1")


# --- TradeStats returns --------------------------------------------------------


def test_trade_stats_records_returns():
    """mean_return and return_variance aggregate the recorded returns."""
    stats = TradeStats(min_sample=1)
    for r in [D("0.01"), D("0.02"), D("-0.01")]:
        stats.record(D("0"), r)  # pnl irrelevant here
    assert stats.has_returns
    assert stats.mean_return > D("0")  # (0.01+0.02-0.01)/3 > 0
    assert stats.return_variance > D("0")


def test_trade_stats_variance_requires_two_samples():
    """A single return yields zero variance."""
    stats = TradeStats(min_sample=1)
    stats.record(D("0"), D("0.01"))
    assert stats.return_variance == D("0")


def test_trade_stats_continuous_kelly_from_returns():
    """continuous_kelly_fraction uses rolling returns, not the binary win/loss."""
    stats = TradeStats(min_sample=2)
    for r in [D("0.02"), D("0.01"), D("0.03")]:
        stats.record(D("10"), r)
    full = stats.continuous_kelly_fraction(D("1.0"))
    half = stats.continuous_kelly_fraction(D("0.5"))
    assert half == full * D("0.5")
    assert full > D("0")
