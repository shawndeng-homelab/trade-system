"""Corrections for realized-equity reporting in the optopsy 2.3 simulator."""

from dataclasses import replace

import pandas as pd


def correct_drawdown(result, capital: float):
    """Return a result whose drawdown includes initial capital and daily closes.

    Preserve the upstream trading model. This is realized equity, not a
    mark-to-market valuation. Do not patch optopsy or mutate its input result.
    """
    summary = dict(result.summary)
    log = result.trade_log
    if not log.empty:
        pnl = log.groupby(pd.to_datetime(log["exit_date"]))["realized_pnl"].sum().sort_index()
        equity = capital + pnl.cumsum()
        summary["max_drawdown"] = float((equity / equity.cummax().clip(lower=capital) - 1).min())
    legs = getattr(result, "leg_results", None)
    if legs is None:
        return replace(result, summary=summary)
    corrected = {}
    for name, leg in legs.items():
        if leg.trade_log.empty:
            corrected[name] = leg
            continue
        first = leg.trade_log.iloc[0]
        leg_capital = float(first["equity"] - first["cumulative_pnl"])
        corrected[name] = correct_drawdown(leg, leg_capital)
    return replace(result, summary=summary, leg_results=corrected)
