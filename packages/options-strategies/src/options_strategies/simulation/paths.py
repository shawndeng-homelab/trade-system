"""独立随机流驱动的多标的日线及压力事件。"""

from datetime import date

import numpy as np
import pandas as pd

from options_strategies.simulation.calendar import sessions
from options_strategies.simulation.config import ParameterOverride
from options_strategies.simulation.config import PriceShock
from options_strategies.simulation.config import SimulationConfig


SUBSTEPS = 16
STOCK_COLUMNS = ["underlying_symbol", "quote_date", "open", "high", "low", "close", "volume"]


def market_state(config: SimulationConfig, day: date) -> dict[str, dict[str, float]]:
    """只根据当前日期和公开配置确定市场参数。"""
    result = {
        item.symbol: {
            "realized_volatility": item.realized_volatility,
            "implied_volatility": item.implied_volatility,
            "spread_multiplier": 1.0,
            "price_factor": 1.0,
        }
        for item in config.symbols
    }
    for event in config.events:
        if isinstance(event, PriceShock) and event.date == day:
            for symbol in event.symbols:
                result[symbol]["price_factor"] = event.factor
        if isinstance(event, ParameterOverride) and event.start_date <= day <= event.end_date:
            for symbol in event.symbols:
                for field in ("realized_volatility", "implied_volatility", "spread_multiplier"):
                    value = getattr(event, field)
                    if value is not None:
                        result[symbol][field] = value
    return result


def stock_path(config: SimulationConfig, path_id: int) -> pd.DataFrame:
    """通过 GBM 精确离散子步生成 OHLC，不修改全局随机状态。"""
    if isinstance(path_id, bool) or not isinstance(path_id, int) or not 0 <= path_id < 2**32:
        raise ValueError("path_id 必须是 [0, 2**32) 内的整数")
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([config.seed, path_id, 0])))
    eigenvalues, eigenvectors = np.linalg.eigh(np.array(config.correlation))
    root = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))
    days = sessions(config.start_date, config.end_date)
    prices = np.array([item.initial_price for item in config.symbols])
    drift = np.array([item.mu for item in config.symbols])
    rows = []
    for index, day in enumerate(days):
        opening = prices.copy()
        high, low = prices.copy(), prices.copy()
        if index:
            state = market_state(config, day)
            sigma = np.array([state[item.symbol]["realized_volatility"] for item in config.symbols])
            opening *= np.array([state[item.symbol]["price_factor"] for item in config.symbols])
            dt = (day - days[index - 1]).days / 365 / SUBSTEPS
            normals = rng.standard_normal((SUBSTEPS, len(config.symbols))) @ root.T
            log_changes = (drift - sigma**2 / 2) * dt + sigma * np.sqrt(dt) * normals
            with np.errstate(over="raise", under="ignore", invalid="raise"):
                levels = opening * np.exp(log_changes.cumsum(axis=0))
            if not np.isfinite(levels).all() or (levels <= 0).any():
                raise ValueError(f"路径子步价格溢出或下溢: path={path_id}, date={day}")
            prices = levels[-1]
            high = np.maximum(opening, levels.max(axis=0))
            low = np.minimum(opening, levels.min(axis=0))
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError(f"路径价格溢出或下溢: path={path_id}, date={day}")
        for i, item in enumerate(config.symbols):
            rows.append((item.symbol, pd.Timestamp(day), opening[i], high[i], low[i], prices[i], 0))
    return pd.DataFrame(rows, columns=STOCK_COLUMNS)
