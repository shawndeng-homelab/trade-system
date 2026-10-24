"""美式有限差分定价和独立的 bid/ask 报价模型。"""

import math
from collections import OrderedDict
from datetime import date
from threading import Lock

import QuantLib as ql

from options_strategies.simulation.calendar import qdate
from options_strategies.simulation.config import PricingConfig
from options_strategies.simulation.config import QuoteConfig


VALUATION_LOCK = Lock()


class AmericanPricer:
    """单线程使用的 QuantLib 定价器，离开上下文时恢复全局估值日期。"""

    def __init__(self, config: PricingConfig):
        """保留数值设置，模型采用零分红。"""
        self.config = config
        self._old_date = None
        self._day = None
        self._processes = {}
        self._cache = OrderedDict()
        self._entered = False
        self.cache_hits = 0
        self.solver_calls = 0

    def __enter__(self):
        """保存 QuantLib 全局日期。"""
        if not VALUATION_LOCK.acquire(blocking=False):
            raise RuntimeError("QuantLib 日频定价上下文不能并发或交错使用，请先消费或关闭现有生成器")
        self._old_date = ql.Settings.instance().evaluationDate
        self._day = None
        self._processes.clear()
        self._entered = True
        return self

    def __exit__(self, *args):
        """即使定价失败也恢复原来的日期。"""
        ql.Settings.instance().evaluationDate = self._old_date
        self._entered = False
        self._processes.clear()
        VALUATION_LOCK.release()

    def price(self, day: date, expiry: date, spot: float, strike: float, iv: float, option_type: str) -> dict:
        """返回每份标的的价格及对现价的一阶、二阶导数。"""
        if not self._entered:
            raise RuntimeError("请在 with AmericanPricer(...) 上下文内定价")
        if expiry <= day or option_type not in ("c", "p"):
            raise ValueError("定价需要未到期的 c/p 合约")
        if min(spot, strike, iv) <= 0 or not all(math.isfinite(v) for v in (spot, strike, iv)):
            raise ValueError("现价、行权价和 IV 必须有限且大于零")
        if day != self._day:
            ql.Settings.instance().evaluationDate = qdate(day)
            self._day = day
            self._processes.clear()
        # 零分红、平坦常数利率/IV、Actual365Fixed 下，绝对日期只通过剩余天数进入 PDE。
        # 只缓存完全相同的输入，不量化现价或 IV，也不插值价格。
        cache_key = ((expiry - day).days, spot, strike, iv, option_type)
        if cache_key in self._cache:
            self.cache_hits += 1
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key].copy()

        def engine(refinement, underlying=spot):
            key = (underlying, iv, refinement)
            if key in self._processes:
                return self._processes[key]
            day_count = ql.Actual365Fixed()
            risk_free = ql.YieldTermStructureHandle(ql.FlatForward(qdate(day), self.config.risk_free_rate, day_count))
            dividends = ql.YieldTermStructureHandle(ql.FlatForward(qdate(day), 0.0, day_count))
            volatility = ql.BlackVolTermStructureHandle(
                ql.BlackConstantVol(qdate(day), ql.NullCalendar(), iv, day_count)
            )
            process = ql.BlackScholesMertonProcess(
                ql.QuoteHandle(ql.SimpleQuote(underlying)), dividends, risk_free, volatility
            )
            self._processes[key] = ql.FdBlackScholesVanillaEngine(
                process,
                self.config.time_grid * 2**refinement,
                self.config.price_grid * 2**refinement,
                self.config.damping_steps,
            )
            return self._processes[key]

        payoff = ql.PlainVanillaPayoff(ql.Option.Call if option_type == "c" else ql.Option.Put, strike)
        option = ql.VanillaOption(payoff, ql.AmericanExercise(qdate(day), qdate(expiry)))
        intrinsic = max(0, spot - strike) if option_type == "c" else max(0, strike - spot)
        upper = spot if option_type == "c" else strike
        tolerance = max(0.01, upper * 1e-5)
        for refinement in range(self.config.max_refinements + 1):
            option.setPricingEngine(engine(refinement))
            self.solver_calls += 1
            price, delta, gamma = option.NPV(), option.delta(), option.gamma()
            greeks_method = "native"
            # 提前行权区域的三次插值可能使原生 Gamma 振荡。用同一 PDE 的价格独立求导，
            # 不裁剪 Greeks，也不切换定价模型。0.25% 对称现价扰动保持 IV 和利率不变，
            # 避免把障碍区域微小的价格求解误差放大成二阶导数噪声。
            if math.isfinite(price) and (
                gamma < -1e-4 or not (-0.005 <= delta <= 1.005 if option_type == "c" else -1.005 <= delta <= 0.005)
            ):
                bump = spot * 0.0025
                values = []
                for underlying in (spot - bump, spot + bump):
                    option.setPricingEngine(engine(refinement, underlying))
                    self.solver_calls += 1
                    values.append(option.NPV())
                delta = (values[1] - values[0]) / (2 * bump)
                gamma = (values[1] - 2 * price + values[0]) / bump**2
                greeks_method = "central_difference"
            if (
                all(math.isfinite(v) for v in (price, delta, gamma))
                and max(0, intrinsic - tolerance) <= price <= upper + tolerance
                and (-0.005 <= delta <= 1.005 if option_type == "c" else -1.005 <= delta <= 0.005)
                and gamma >= -1e-4
            ):
                break
        else:
            raise ValueError(f"定价边界检查失败: price={price}, delta={delta}, gamma={gamma}")
        result = {
            "theoretical_price": price,
            "delta": delta,
            "gamma": gamma,
            "pricing_refinement": refinement,
            "greeks_method": greeks_method,
        }
        self._cache[cache_key] = result
        if len(self._cache) > 65536:
            self._cache.popitem(last=False)
        return result.copy()


def make_quote(price: float, config: QuoteConfig, multiplier: float = 1.0) -> dict:
    """以全价差构造报价，使用整数 tick 向外取整。"""
    width = max(config.minimum_spread, price * config.relative_spread) * multiplier
    bid_ticks = math.floor(max(0, price - width / 2) / config.tick_size + 1e-10)
    ask_ticks = math.ceil((price + width / 2) / config.tick_size - 1e-10)
    return {"bid": bid_ticks * config.tick_size, "ask": ask_ticks * config.tick_size}
