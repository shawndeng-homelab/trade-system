"""以数值、合约身份和时间覆盖检查数据，而非仅检查文件存在。"""

import numpy as np
import pandas as pd

from options_strategies.simulation.source import DATE_COLUMNS
from options_strategies.simulation.source import INT_COLUMNS
from options_strategies.simulation.source import STRING_COLUMNS
from options_strategies.simulation.source import TABLE_COLUMNS


def validate_frame(name: str, frame: pd.DataFrame, path_id: int, tick_size: float) -> None:
    """检查单个分片的结构和金融边界。"""
    if list(frame.columns) != TABLE_COLUMNS[name] or frame.isna().any().any():
        raise ValueError(f"{name}: 列结构错误或包含缺失值")
    for column in frame:
        expected_dtype = (
            "datetime64[ns]"
            if column in DATE_COLUMNS
            else "object"
            if column in STRING_COLUMNS
            else "int64"
            if column in INT_COLUMNS
            else "float64"
        )
        if frame[column].dtype != expected_dtype:
            raise ValueError(f"{name}: {column} dtype 应为 {expected_dtype}")
        if column in STRING_COLUMNS and len(frame) and pd.api.types.infer_dtype(frame[column]) != "string":
            raise ValueError(f"{name}: {column} 应为字符串")
    numeric = frame.select_dtypes(include="number")
    if not np.isfinite(numeric.to_numpy()).all() or not frame.path_id.eq(path_id).all():
        raise ValueError(f"{name}: 非有限值或路径编号错误")
    if frame.empty:
        return
    if name == "stock":
        if frame.duplicated(["underlying_symbol", "quote_date"]).any():
            raise ValueError("stock: 重复日期/标的")
        if (
            (frame[["open", "high", "low", "close"]] <= 0).any().any()
            or (frame.high < frame[["open", "close", "low"]].max(axis=1)).any()
            or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any()
        ):
            raise ValueError("stock: OHLC 关系错误")
    elif name == "contracts":
        if (
            frame.contract_id.duplicated().any()
            or frame.duplicated(["underlying_symbol", "expiration", "option_type", "strike"]).any()
            or (frame.listed_date >= frame.expiration).any()
            or not frame.option_type.isin(["c", "p"]).all()
            or not frame.expiration_type.isin(["monthly", "weekly"]).all()
        ):
            raise ValueError("contracts: 合约重复或生命周期错误")
        if (frame.strike <= 0).any() or (frame.multiplier <= 0).any():
            raise ValueError("contracts: 行权价或乘数错误")
    elif name == "options":
        if frame.duplicated(["quote_date", "contract_id"]).any() or (frame.quote_date >= frame.expiration).any():
            raise ValueError("options: 报价重复或已到期")
        call = frame.option_type.eq("c")
        if not frame.option_type.isin(["c", "p"]).all():
            raise ValueError("options: 未知期权类型")
        intrinsic = np.maximum(
            np.where(call, frame.underlying_price - frame.strike, frame.strike - frame.underlying_price), 0
        )
        upper = np.where(call, frame.underlying_price, frame.strike)
        tolerance = np.maximum(0.01, upper * 1e-5)
        if (
            (frame.implied_volatility <= 0).any()
            or (frame.theoretical_price < 0).any()
            or (frame.theoretical_price < intrinsic - tolerance).any()
            or (frame.theoretical_price > upper + tolerance).any()
            or (frame.bid < 0).any()
            or (frame.bid > frame.theoretical_price + 1e-9).any()
            or (frame.ask < frame.theoretical_price - 1e-9).any()
            or (frame.delta < np.where(call, -0.005, -1.005)).any()
            or (frame.delta > np.where(call, 1.005, 0.005)).any()
            or (frame.gamma < -1e-4).any()
            or not frame.greeks_method.isin(["native", "central_difference"]).all()
            or not np.allclose(
                frame[["bid", "ask"]] / tick_size, np.round(frame[["bid", "ask"]] / tick_size), rtol=0, atol=1e-6
            )
        ):
            raise ValueError("options: 价格、Greeks 或报价边界错误")
    elif name == "settlements":
        if (frame.quote_date != frame.expiration).any() or frame.contract_id.duplicated().any():
            raise ValueError("settlements: 结算日期或合约错误")
        expected = np.maximum(
            np.where(
                frame.option_type.eq("c"), frame.underlying_price - frame.strike, frame.strike - frame.underlying_price
            ),
            0,
        )
        if not np.allclose(frame.settlement_price, expected, rtol=0, atol=1e-10):
            raise ValueError("settlements: 内在价值错误")
