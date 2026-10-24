"""合成市场的版本化配置，所有金融假设由调用方显式提供。"""

import hashlib
import json
from datetime import date
from typing import Annotated
from typing import Literal

import numpy as np
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from options_strategies.simulation.calendar import is_session
from options_strategies.simulation.calendar import sessions


class ConfigModel(BaseModel):
    """禁止未知字段、非有限数值和原地修改。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SymbolConfig(ConfigModel):
    """单标的市场假设；收益率和波动率均使用年化小数。"""

    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,15}$")
    initial_price: float = Field(gt=0)
    mu: float
    realized_volatility: float = Field(ge=0)
    implied_volatility: float = Field(gt=0)
    strike_step: float = Field(5.0, gt=0)
    multiplier: int = Field(100, gt=0)


class ChainConfig(ConfigModel):
    """按现价持续补充行权价，已上市合约保留到期。"""

    weekly_expirations: int = Field(8, ge=0)
    monthly_expirations: int = Field(24, ge=0)
    strike_lower: float = Field(0.5, gt=0, lt=1)
    strike_upper: float = Field(1.5, gt=1)

    @model_validator(mode="after")
    def validate_expirations(self):
        """至少生成一种到期日。"""
        if self.weekly_expirations + self.monthly_expirations == 0:
            raise ValueError("至少需要一种到期日")
        return self


class PricingConfig(ConfigModel):
    """美式有限差分网格；利率为连续复利年化利率。"""

    risk_free_rate: float
    time_grid: int = Field(200, ge=20)
    price_grid: int = Field(400, ge=40)
    damping_steps: int = Field(2, ge=0)
    max_refinements: int = Field(2, ge=0, le=3)


class QuoteConfig(ConfigModel):
    """每份标的的全价差及报价 tick。"""

    minimum_spread: float = Field(0.10, ge=0)
    relative_spread: float = Field(0.02, ge=0)
    tick_size: float = Field(0.01, gt=0)


class PriceShock(ConfigModel):
    """交易日开盘的一次性乘数冲击。"""

    kind: Literal["price_shock"] = "price_shock"
    date: date
    symbols: tuple[str, ...] = Field(min_length=1)
    factor: float = Field(gt=0)


class ParameterOverride(ConfigModel):
    """闭区间内覆盖参数，区间结束后回到基线。"""

    kind: Literal["parameter_override"] = "parameter_override"
    start_date: date
    end_date: date
    symbols: tuple[str, ...] = Field(min_length=1)
    realized_volatility: float | None = Field(None, ge=0)
    implied_volatility: float | None = Field(None, gt=0)
    spread_multiplier: float | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_override(self):
        """验证区间以及至少一项有效覆盖。"""
        if self.start_date > self.end_date:
            raise ValueError("参数覆盖开始日期不能晚于结束日期")
        if all(getattr(self, name) is None for name in OVERRIDE_FIELDS):
            raise ValueError("参数覆盖至少需要一个参数")
        return self


OVERRIDE_FIELDS = ("realized_volatility", "implied_volatility", "spread_multiplier")
MarketEvent = Annotated[PriceShock | ParameterOverride, Field(discriminator="kind")]


class SimulationConfig(ConfigModel):
    """完整实验配置；标的顺序同时决定相关矩阵的行列顺序。"""

    schema_version: Literal[1] = 1
    start_date: date
    end_date: date
    symbols: tuple[SymbolConfig, ...] = Field(min_length=1)
    correlation: tuple[tuple[float, ...], ...]
    pricing: PricingConfig
    seed: int = Field(42, ge=0, le=2**64 - 1)
    n_paths: int = Field(1, gt=0)
    chunk_sessions: int = Field(5, gt=0)
    chain: ChainConfig = ChainConfig()
    quotes: QuoteConfig = QuoteConfig()
    events: tuple[MarketEvent, ...] = ()
    cash_dividends: tuple = ()

    @model_validator(mode="after")
    def validate_market(self):
        """在生成前验证时钟、矩阵及事件冲突。"""
        names = [item.symbol for item in self.symbols]
        if len(set(names)) != len(names):
            raise ValueError("标的不能重复")
        if self.start_date > self.end_date or not sessions(self.start_date, self.end_date):
            raise ValueError("日期范围必须包含交易日且开始日期不能晚于结束日期")
        if self.cash_dividends:
            raise ValueError("首版不支持非空分红日程")
        matrix = np.asarray(self.correlation, dtype=float)
        if matrix.shape != (len(names), len(names)) or not np.isfinite(matrix).all():
            raise ValueError("相关矩阵维度不匹配或包含非有限数值")
        if (
            not np.allclose(matrix, matrix.T, atol=1e-12, rtol=0)
            or not np.allclose(matrix.diagonal(), 1, atol=1e-12, rtol=0)
            or np.max(np.abs(matrix)) > 1 + 1e-12
            or np.linalg.eigvalsh(matrix).min() < -1e-12
        ):
            raise ValueError("相关矩阵必须对称、半正定、对角线为 1")
        occupied = {}
        for event in self.events:
            if len(set(event.symbols)) != len(event.symbols) or not set(event.symbols) <= set(names):
                raise ValueError("事件包含重复或未配置的标的")
            left = event.date if isinstance(event, PriceShock) else event.start_date
            right = event.date if isinstance(event, PriceShock) else event.end_date
            if left < self.start_date or right > self.end_date or not is_session(left) or not is_session(right):
                raise ValueError("事件日期必须位于模拟区间内且为交易日")
            if isinstance(event, PriceShock) and left == sessions(self.start_date, self.end_date)[0]:
                raise ValueError("首日为初始价格锚点，价格冲击必须在后续交易日")
            fields = ("price",) if isinstance(event, PriceShock) else OVERRIDE_FIELDS
            for symbol in event.symbols:
                for name in fields:
                    if name != "price" and getattr(event, name) is None:
                        continue
                    key = (symbol, name)
                    if any(
                        left <= previous_end and right >= previous_start
                        for previous_start, previous_end in occupied.get(key, [])
                    ):
                        raise ValueError(f"事件区间冲突: {symbol}/{name}")
                    occupied.setdefault(key, []).append((left, right))
        return self

    def fingerprint(self) -> str:
        """返回顺序稳定的配置摘要。"""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
