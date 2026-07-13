"""PMCC (Poor Man's Covered Call): long deep-ITM LEAPS call + short near-term OTM call."""

from trade_system_strategies.pmcc.config import PMCCConfig
from trade_system_strategies.pmcc.signals import PMCCAction
from trade_system_strategies.pmcc.signals import pmcc_entry_decision
from trade_system_strategies.pmcc.signals import pmcc_leaps_decision
from trade_system_strategies.pmcc.signals import pmcc_roll_config_from_pmcc_config
from trade_system_strategies.pmcc.signals import pmcc_short_call_decision
from trade_system_strategies.pmcc.signals import select_leaps_roll_target
from trade_system_strategies.pmcc.signals import select_short_call_roll_target
from trade_system_strategies.pmcc.strategy import PMCCStrategy


__all__ = [
    "PMCCAction",
    "PMCCConfig",
    "PMCCStrategy",
    "pmcc_entry_decision",
    "pmcc_leaps_decision",
    "pmcc_roll_config_from_pmcc_config",
    "pmcc_short_call_decision",
    "select_leaps_roll_target",
    "select_short_call_roll_target",
]
