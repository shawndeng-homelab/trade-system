"""Curve-based reporting metrics, including the initial capital baseline."""

import math

import pandas as pd


def curve_metrics(curve: pd.Series, capital: float) -> dict:
    """Calculate metrics over exactly the displayed curve and its starting capital.

    These describe the supplied equity series, not unobserved intraday or
    unrealized changes. Undefined annualized returns and ratios remain missing.
    """
    if curve.empty:
        return {}
    total_return = float(curve.iloc[-1] / capital - 1)
    peaks = curve.cummax().clip(lower=capital)
    drawdown = float((curve / peaks - 1).min())
    years = (curve.index[-1] - curve.index[0]).total_seconds() / (365.25 * 86400)
    annualized = None
    if years > 0 and total_return >= -1:
        try:
            candidate = (1 + total_return) ** (1 / years) - 1
            if math.isfinite(candidate):
                annualized = candidate
        except OverflowError:
            pass
    return {
        "total_return": total_return,
        "total_pnl": float(curve.iloc[-1] - capital),
        "max_drawdown": drawdown,
        "annualized_return": annualized,
        "mar_ratio": annualized / abs(drawdown) if annualized is not None and drawdown < 0 else None,
    }
