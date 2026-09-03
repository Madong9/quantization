from __future__ import annotations  # 允许使用 list[list[float]] 这类类型注解

from typing import Optional  # 表示函数可能返回字符串，也可能返回 None

from config import FAST_EMA, SLOW_EMA  # 导入快慢 EMA 周期
from strategy.ema import ema  # 导入 EMA 计算函数


def detect_signal(candles: list[list[float]]) -> Optional[str]:  # 定义函数：根据 EMA 交叉检测买卖信号
    closes = [float(candle[4]) for candle in candles]  # 从每根 K 线中提取收盘价，ccxt OHLCV 的第 5 项是 close
    fast = ema(closes, FAST_EMA)  # 计算 10 EMA 快线
    slow = ema(closes, SLOW_EMA)  # 计算 30 EMA 慢线

    prev_fast, curr_fast = fast[-2], fast[-1]  # 取上一根和当前收盘 K 线对应的快线 EMA
    prev_slow, curr_slow = slow[-2], slow[-1]  # 取上一根和当前收盘 K 线对应的慢线 EMA

    if prev_fast <= prev_slow and curr_fast > curr_slow:  # 快线从慢线下方或相等位置上穿到慢线上方
        return "buy"  # 返回买入信号，模拟做多
    if prev_fast >= prev_slow and curr_fast < curr_slow:  # 快线从慢线上方或相等位置下穿到慢线下方
        return "sell"  # 返回卖出信号，模拟做空
    return None  # 没有发生交叉时，不返回交易信号


