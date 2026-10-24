"""美股日频交易时钟；日期标签代表交易日收盘。"""

from datetime import date
from datetime import timedelta

import QuantLib as ql


CALENDAR = ql.UnitedStates(ql.UnitedStates.NYSE)


def qdate(value: date) -> ql.Date:
    """转换为 QuantLib 日期。"""
    return ql.Date(value.day, value.month, value.year)


def is_session(value: date) -> bool:
    """判断是否为 NYSE 交易日。"""
    return CALENDAR.isBusinessDay(qdate(value))


def sessions(start: date, end: date) -> list[date]:
    """列出闭区间内的交易日。"""
    result = []
    current = start
    while current <= end:
        if is_session(current):
            result.append(current)
        current += timedelta(days=1)
    return result


def preceding_session(value: date) -> date:
    """将休市日向前调整到交易日。"""
    return CALENDAR.adjust(qdate(value), ql.Preceding).to_date()
