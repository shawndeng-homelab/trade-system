"""Kelly-criterion position sizing helpers.

Pure functions and a rolling realized-PnL accumulator, engine-free so they can be unit-
tested and reused across strategies and research notebooks. Kelly sizes a position from
an estimated edge (win rate and payoff ratio); the :class:`TradeStats` accumulator turns
a stream of closed-trade PnLs into those edge estimates, optionally over a rolling window.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal


ZERO = Decimal("0")
ONE = Decimal("1")


def kelly_fraction(
    win_rate: Decimal,
    avg_win: Decimal,
    avg_loss: Decimal,
) -> Decimal:
    """Return the full Kelly fraction ``f* = W - (1-W)/R``.

    ``R = avg_win / |avg_loss|`` is the win/loss payoff ratio. A non-positive result
    means no statistical edge, so it is clamped to zero (do not trade).

    Args:
        win_rate: Fraction of trades that were winners, in ``[0, 1]``.
        avg_win: Average profit per winning trade (positive).
        avg_loss: Average loss per losing trade (negative); sign is taken internally.

    Returns:
        The full Kelly fraction ``f*`` in ``[0, 1]`` (unclamped above by default).

    Raises:
        ZeroDivisionError: Never — a zero ``avg_loss`` yields ``0`` (edge undefined).

    """
    if avg_loss == 0 or avg_win <= 0:
        return ZERO
    payoff = avg_win / abs(avg_loss)
    fraction = win_rate - (ONE - win_rate) / payoff
    return fraction if fraction > ZERO else ZERO


def fractional_kelly(
    win_rate: Decimal,
    avg_win: Decimal,
    avg_loss: Decimal,
    fraction: Decimal = Decimal("0.5"),
    max_fraction: Decimal | None = None,
) -> Decimal:
    """Return a scaled Kelly fraction (e.g. half-Kelly), optionally capped.

    Args:
        win_rate: Fraction of trades that were winners.
        avg_win: Average profit per winning trade (positive).
        avg_loss: Average loss per losing trade (negative).
        fraction: Scaling factor on full Kelly (``0.5`` = half-Kelly, the standard
            risk-control default).
        max_fraction: Optional hard cap on the scaled fraction (e.g. ``0.25`` to never
            risk more than 25% of equity on one trade).

    Returns:
        The scaled Kelly fraction, clamped to ``[0, max_fraction]``.

    """
    scaled = kelly_fraction(win_rate, avg_win, avg_loss) * fraction
    if max_fraction is not None:
        scaled = min(scaled, max_fraction)
    return scaled if scaled > ZERO else ZERO


def kelly_position_size(
    equity: Decimal,
    price: Decimal,
    win_rate: Decimal,
    avg_win: Decimal,
    avg_loss: Decimal,
    fraction: Decimal = Decimal("0.5"),
    max_fraction: Decimal | None = None,
) -> Decimal:
    """Return the number of units to trade for a Kelly-sized position.

    ``units = equity * kelly_fraction / price``. A zero result means "no edge, skip".

    Args:
        equity: Account equity in the quote currency.
        price: Current price per unit of the instrument.
        win_rate: Fraction of trades that were winners.
        avg_win: Average profit per winning trade (positive).
        avg_loss: Average loss per losing trade (negative).
        fraction: Scaling factor on full Kelly.
        max_fraction: Optional hard cap on the fraction of equity deployed.

    Returns:
        Units (shares/contracts) to trade, or ``0`` if no edge or non-positive price.

    """
    if price <= 0 or equity <= 0:
        return ZERO
    fr = fractional_kelly(win_rate, avg_win, avg_loss, fraction, max_fraction)
    return (equity * fr) / price


def continuous_kelly_fraction(
    mean_return: Decimal,
    variance: Decimal,
    fraction: Decimal = Decimal("0.5"),
    max_fraction: Decimal | None = None,
) -> Decimal:
    """Return the continuous (Gaussian) Kelly fraction ``f* = mean / variance``.

    Unlike the discrete win/loss Kelly, this uses the full return distribution's mean and
    variance, so it captures payoff asymmetry (large wins vs small losses) that the
    binary form discards. Suited to strategies whose per-trade PnL is a continuous return.

    Args:
        mean_return: Mean per-trade return (e.g. 0.01 for 1%).
        variance: Variance of per-trade returns. Zero or negative is degenerate -> 0.
        fraction: Scaling factor on full Kelly (``0.5`` = half-Kelly).
        max_fraction: Optional hard cap on the scaled fraction.

    Returns:
        The scaled continuous Kelly fraction, clamped to ``[0, max_fraction]``; ``0`` if
        no edge (mean <= 0) or variance undefined.

    """
    if variance <= 0 or mean_return <= 0:
        return ZERO
    scaled = (mean_return / variance) * fraction
    if max_fraction is not None:
        scaled = min(scaled, max_fraction)
    return scaled if scaled > ZERO else ZERO


def drawdown_scalar(
    drawdown: Decimal,
    max_drawdown: Decimal,
    floor: Decimal = ZERO,
) -> Decimal:
    """Return a linear scaling factor that shrinks exposure as drawdown deepens.

    ``scalar = 1 - drawdown / max_drawdown``, clamped to ``[floor, 1]``. At zero drawdown
    the factor is 1 (full size); at ``max_drawdown`` it hits ``floor`` (e.g. stop trading
    new entries). Use to scale a Kelly fraction down during losing streaks.

    Args:
        drawdown: Current drawdown as a fraction in ``[0, 1]`` (0 = at peak).
        max_drawdown: Drawdown at which exposure floors out, in ``(0, 1]``.
        floor: Minimum scalar (e.g. ``0`` to fully stop, ``0.25`` to keep a quarter size).

    Returns:
        A scalar in ``[floor, 1]``.

    """
    if max_drawdown <= 0:
        return ONE
    scalar = ONE - drawdown / max_drawdown
    if scalar < floor:
        return floor
    if scalar > ONE:
        return ONE
    return scalar


@dataclass
class TradeStats:
    """Rolling accumulator of realized per-trade PnL and returns for Kelly estimation.

    Attributes:
        window: Max trades retained (rolling). ``None`` keeps the full history.
        min_sample: Trades required before :attr:`ready` is True.

    """

    window: int | None = None
    min_sample: int = 10
    _pnls: deque = field(default_factory=deque)
    _returns: deque = field(default_factory=deque)

    def __post_init__(self) -> None:
        """Bind the rolling windows to the deques' maxlen."""
        self._pnls = deque(maxlen=self.window)
        self._returns = deque(maxlen=self.window)

    def record(self, pnl: Decimal, return_value: Decimal | None = None) -> None:
        """Record one closed trade's realized PnL (signed) and optional return.

        Args:
            pnl: Realized PnL in account currency (signed).
            return_value: Per-trade return fraction (e.g. 0.01 for +1%). When provided,
                enables the continuous-Kelly estimators (:meth:`mean_return`,
                :meth:`return_variance`).

        """
        self._pnls.append(pnl)
        if return_value is not None:
            self._returns.append(return_value)

    @property
    def ready(self) -> bool:
        """Whether enough trades have been recorded to estimate edge."""
        return len(self._pnls) >= self.min_sample

    @property
    def count(self) -> int:
        """Number of recorded trades currently in the window."""
        return len(self._pnls)

    @property
    def has_returns(self) -> bool:
        """Whether per-trade returns have been recorded."""
        return bool(self._returns)

    @property
    def win_rate(self) -> Decimal:
        """Fraction of recorded trades that were winners (``0`` if empty)."""
        if not self._pnls:
            return ZERO
        wins = sum(1 for p in self._pnls if p > 0)
        return Decimal(wins) / Decimal(len(self._pnls))

    @property
    def avg_win(self) -> Decimal:
        """Average profit across winning trades (``0`` if none)."""
        wins = [p for p in self._pnls if p > 0]
        if not wins:
            return ZERO
        return sum(wins, start=ZERO) / Decimal(len(wins))

    @property
    def avg_loss(self) -> Decimal:
        """Average loss across losing trades (negative; ``0`` if none)."""
        losses = [p for p in self._pnls if p < 0]
        if not losses:
            return ZERO
        return sum(losses, start=ZERO) / Decimal(len(losses))

    @property
    def mean_return(self) -> Decimal:
        """Mean of recorded per-trade returns (``0`` if none)."""
        if not self._returns:
            return ZERO
        return sum(self._returns, start=ZERO) / Decimal(len(self._returns))

    @property
    def return_variance(self) -> Decimal:
        """Population variance of recorded per-trade returns (``0`` if < 2 samples)."""
        if len(self._returns) < 2:
            return ZERO
        mu = self.mean_return
        sq = sum((r - mu) ** 2 for r in self._returns)
        return sq / Decimal(len(self._returns))

    def kelly_fraction(self, fraction: Decimal = Decimal("0.5"), max_fraction: Decimal | None = None) -> Decimal:
        """Return the scaled discrete (win/loss) Kelly fraction from rolling stats."""
        return fractional_kelly(self.win_rate, self.avg_win, self.avg_loss, fraction, max_fraction)

    def continuous_kelly_fraction(
        self,
        fraction: Decimal = Decimal("0.5"),
        max_fraction: Decimal | None = None,
    ) -> Decimal:
        """Return the scaled continuous (Gaussian) Kelly fraction from rolling returns.

        Falls back to ``0`` when no returns have been recorded.
        """
        return continuous_kelly_fraction(self.mean_return, self.return_variance, fraction, max_fraction)
