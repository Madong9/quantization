from __future__ import annotations  # 允许使用 list[list[float]] 这类类型注解

import ccxt  # 使用 ccxt 的 Binance 类型

from config import SLOW_EMA, SYMBOL, TIMEFRAME  # 导入交易对、周期和慢 EMA 参数


def fetch_closed_candles(exchange: ccxt.binance) -> list[list[float]]:  # 定义函数：获取已经收盘的 K 线
    candles = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)  # 拉取最近 100 根指定周期 K 线
    if len(candles) < SLOW_EMA + 2:  # 至少需要慢 EMA 周期加 2 根，才能判断前后两根交叉
        raise RuntimeError("Not enough candles returned by exchange")  # K 线不足时抛出运行时错误

    # 最新一根 K 线可能仍在形成中，去掉它可以避免盘中假信号。  # 解释为什么丢弃最后一根
    return candles[:-1]  # 返回除最后一根以外的已收盘 K 线
