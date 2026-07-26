"""PMCC strategy — long LEAPS + short near-term call via optopsy."""

from options_strategies.pmcc.config import PmccConfig
from options_strategies.pmcc.signals import leaps_entry_dates
from options_strategies.pmcc.signals import short_call_entry_dates
from options_strategies.pmcc.strategy import run_pmcc


__all__ = [
    "PmccConfig",
    "leaps_entry_dates",
    "run_pmcc",
    "short_call_entry_dates",
]
