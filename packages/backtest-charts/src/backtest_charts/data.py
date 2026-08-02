"""Data extraction and validation layer for backtest-charts.

Provides :class:`BacktestData` and :class:`LegData` — frozen dataclasses
that pre-extract and normalize data from any duck-typed result object
(e.g. ``optopsy.PortfolioResult`` or ``types.SimpleNamespace``).

Chart functions accept ``BacktestData`` instead of raw result objects,
decoupling visualization from optopsy internals.
"""

import dataclasses
import typing

import pandas as pd


@dataclasses.dataclass(frozen=True)
class LegData:
    """Pre-extracted per-leg backtest data.

    Attributes:
        name: Leg identifier (e.g. ``"leaps"``, ``"short_call"``).
        trade_log: Per-leg trade log DataFrame.
        equity_curve: Per-leg equity curve (date-indexed Series).
        summary: Per-leg summary metrics dict.
    """

    name: str
    trade_log: pd.DataFrame
    equity_curve: pd.Series
    summary: dict


@dataclasses.dataclass(frozen=True)
class BacktestData:
    """Pre-extracted, validated backtest data for chart rendering.

    Constructed via :meth:`from_result` which validates and normalizes
    data from any duck-typed result object.  Once constructed, chart
    functions can rely on fields without re-validating.

    Attributes:
        capital: Initial capital for reference lines.
        equity_curve: Portfolio equity curve (date-indexed Series, may be empty).
        trade_log: Combined trade log DataFrame (may be empty).
        summary: Portfolio-level summary metrics dict.
        leg_names: Ordered list of leg identifiers.
        leg_results: Per-leg data keyed by leg name.
    """

    capital: float
    equity_curve: pd.Series
    trade_log: pd.DataFrame
    summary: dict
    leg_names: list[str]
    leg_results: dict[str, LegData]
    # Private: stored for backward-compat panel wrappers only.
    # Not part of the public API — new code should use BacktestData fields.
    _raw: typing.Any = dataclasses.field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate capital is positive."""
        if self.capital <= 0:
            msg = f"capital must be positive, got {self.capital}"
            raise ValueError(msg)

    @property
    def has_trades(self) -> bool:
        """Whether the trade log contains any trades."""
        return not self.trade_log.empty

    @property
    def has_equity(self) -> bool:
        """Whether the equity curve has data points."""
        return self.equity_curve is not None and not self.equity_curve.empty

    @classmethod
    def from_result(cls, result, capital: float) -> "BacktestData":
        """Extract and validate data from a duck-typed result object.

        Accepts any object with ``equity_curve``, ``trade_log``,
        ``summary``, and ``leg_results`` attributes.  Missing attributes
        default to empty values.

        Args:
            result: Backtest result (e.g. ``optopsy.PortfolioResult``).
            capital: Initial capital for reference lines.

        Returns:
            Frozen ``BacktestData`` instance.
        """
        # Equity curve
        ec = getattr(result, "equity_curve", None)
        if ec is None or (isinstance(ec, pd.Series) and ec.empty):
            ec = pd.Series(dtype=float, name="equity")
        elif isinstance(ec, pd.Series):
            ec = ec.copy()
            ec.index = pd.to_datetime(ec.index)

        # Trade log
        tl = getattr(result, "trade_log", None)
        tl = pd.DataFrame() if tl is None else tl.copy()

        # Summary
        summary = getattr(result, "summary", None) or {"total_trades": 0}

        # Leg results
        raw_legs = getattr(result, "leg_results", None) or {}
        leg_names: list[str] = []
        leg_results: dict[str, LegData] = {}
        for name, leg in raw_legs.items():
            leg_ec = getattr(leg, "equity_curve", None)
            if leg_ec is None or (isinstance(leg_ec, pd.Series) and leg_ec.empty):
                leg_ec = pd.Series(dtype=float, name="equity")
            elif isinstance(leg_ec, pd.Series):
                leg_ec = leg_ec.copy()
                leg_ec.index = pd.to_datetime(leg_ec.index)

            leg_tl = getattr(leg, "trade_log", None)
            leg_tl = pd.DataFrame() if leg_tl is None else leg_tl.copy()

            leg_summary = getattr(leg, "summary", None) or {"total_trades": 0}

            leg_names.append(str(name))
            leg_results[str(name)] = LegData(
                name=str(name),
                trade_log=leg_tl,
                equity_curve=leg_ec,
                summary=leg_summary,
            )

        return cls(
            capital=capital,
            equity_curve=ec,
            trade_log=tl,
            summary=summary,
            leg_names=leg_names,
            leg_results=leg_results,
            _raw=result,
        )
