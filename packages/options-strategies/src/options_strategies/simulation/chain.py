"""合成期权挂牌和存续规则，不使用未来价格。"""

import calendar
import math
from datetime import date
from datetime import timedelta

from options_strategies.simulation.calendar import preceding_session
from options_strategies.simulation.config import ChainConfig
from options_strategies.simulation.config import SymbolConfig


CONTRACT_COLUMNS = [
    "contract_id",
    "underlying_symbol",
    "option_type",
    "expiration",
    "strike",
    "expiration_type",
    "listed_date",
    "multiplier",
]


def expirations(day: date, config: ChainConfig) -> dict[date, str]:
    """生成未来周五和第三个周五到期日，月度标记优先。"""
    result = {}
    friday = day + timedelta(days=(4 - day.weekday()) % 7)
    found = 0
    while found < config.weekly_expirations:
        expiry = preceding_session(friday)
        if expiry > day:
            result[expiry] = "weekly"
            found += 1
        friday += timedelta(days=7)
    year, month = day.year, day.month
    found = 0
    while found < config.monthly_expirations:
        first_weekday = calendar.monthrange(year, month)[0]
        expiry = preceding_session(date(year, month, 1 + (4 - first_weekday) % 7 + 14))
        if expiry > day:
            result[expiry] = "monthly"
            found += 1
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


class ContractBook:
    """使用整数行权价格点保存身份稳定的合约。"""

    def __init__(self, config: ChainConfig):
        """建立空合约簿。"""
        self.config = config
        self.active = {}

    def list_contracts(self, day: date, symbol: SymbolConfig, spot: float) -> list[dict]:
        """补充当日缺失格点，返回新上市合约。"""
        lower = max(1, math.ceil(spot * self.config.strike_lower / symbol.strike_step))
        upper = math.floor(spot * self.config.strike_upper / symbol.strike_step)
        if lower > upper:
            raise ValueError(f"行权价格点为空: {symbol.symbol}/{day}; 请减小 strike_step")
        additions = []
        for expiry, kind in sorted(expirations(day, self.config).items()):
            for grid in range(lower, upper + 1):
                for option_type in ("c", "p"):
                    identity = f"{symbol.symbol}:{expiry.isoformat()}:{option_type}:{grid}"
                    if identity not in self.active:
                        contract = {
                            "contract_id": identity,
                            "underlying_symbol": symbol.symbol,
                            "option_type": option_type,
                            "expiration": expiry,
                            "strike": grid * symbol.strike_step,
                            "expiration_type": kind,
                            "listed_date": day,
                            "multiplier": symbol.multiplier,
                        }
                        self.active[identity] = contract
                        additions.append(contract)
        return additions

    def retire(self, day: date) -> None:
        """结算后移除到期合约。"""
        self.active = {key: item for key, item in self.active.items() if item["expiration"] > day}
