from __future__ import annotations  # 允许使用更现代的类型注解写法


def ema(values: list[float], period: int) -> list[float]:  # 定义函数：计算 EMA 数组
    if len(values) < period:  # 如果收盘价数量少于 EMA 周期，就无法计算
        raise ValueError(f"Need at least {period} candles to calculate EMA")  # 抛出明确错误

    multiplier = 2 / (period + 1)  # EMA 平滑系数，标准公式为 2 / (周期 + 1)
    ema_values: list[float] = []  # 创建列表，用来保存每根 K 线对应的 EMA
    previous = sum(values[:period]) / period  # 用前 period 个价格的简单平均值作为初始 EMA
    ema_values.extend([previous] * period)  # 前 period 个位置填入初始 EMA，保证长度和价格列表对齐

    for price in values[period:]:  # 从第 period 个价格之后开始逐个递推 EMA
        previous = (price - previous) * multiplier + previous  # 使用 EMA 递推公式计算最新 EMA
        ema_values.append(previous)  # 把本次计算出的 EMA 追加到结果列表

    return ema_values  # 返回完整 EMA 列表
