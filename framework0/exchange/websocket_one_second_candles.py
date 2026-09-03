from __future__ import annotations  # 允许使用更现代的类型注解写法

import asyncio  # 用于 WebSocket 重连等待
import json  # 解析 WebSocket 返回的 JSON 消息
import os  # 读取环境变量，用来判断是否使用测试网
from collections import deque  # 用固定长度队列保存最近的闭合 K 线
from collections.abc import AsyncIterator  # 标注异步迭代器返回类型

import websockets  # 连接 Binance WebSocket

from config import BINANCE_TESTNET_ENV, FUTURES_TESTNET_WS_BASE_URL, FUTURES_WS_BASE_URL  # 导入 Binance 合约 WebSocket 基础地址


IDLE_TIMEOUT_SECONDS = 10  # WebSocket 超过 10 秒没有成交消息时打印提示


def symbol_to_stream_name(symbol: str) -> str:  # 定义函数：把 ccxt 合约交易对转成 Binance stream 名称
    return symbol.split(":")[0].replace("/", "").lower()  # 例如 ETH/USDT:USDT 转成 ethusdt


def get_futures_ws_base_url() -> str:  # 定义函数：根据环境变量选择主网或测试网 WebSocket 地址
    if os.getenv(BINANCE_TESTNET_ENV, "").lower() == "true":  # 如果用户启用了 Binance 测试网
        return FUTURES_TESTNET_WS_BASE_URL  # 返回 Binance Futures 测试网 WebSocket 地址
    return FUTURES_WS_BASE_URL  # 默认返回 Binance Futures 主网 WebSocket 地址


class WebSocketOneSecondCandles:  # 定义类：用 Binance aggTrade WebSocket 聚合 1 秒 K 线
    def __init__(self, symbol: str, max_candles: int = 1200) -> None:  # 初始化 WebSocket 秒线聚合器
        self.symbol = symbol  # 保存 ccxt 格式交易对
        self.stream_name = symbol_to_stream_name(symbol)  # 保存 Binance stream 名称
        self.max_candles = max_candles  # 保存最多保留多少根闭合 K 线
        self.closed_candles: deque[list[float]] = deque(maxlen=max_candles)  # 保存闭合 K 线
        self.current_candle: list[float] | None = None  # 保存正在形成的当前秒 K 线
        self.last_close_price: float | None = None  # 保存上一根闭合 K 线收盘价，用于填补无成交秒

    @property  # 把 WebSocket URL 做成只读属性
    def url(self) -> str:  # 定义函数：返回 Binance USD-M Futures aggTrade WebSocket 地址
        return f"{get_futures_ws_base_url()}/{self.stream_name}@aggTrade"  # 返回 USD-M Futures 单流地址

    def update_with_trade(self, price: float, quantity: float, trade_time_ms: int) -> bool:  # 定义函数：用一笔成交更新秒线
        candle_ts = (trade_time_ms // 1000) * 1000  # 把成交时间截断到秒，作为 K 线开始时间

        if self.current_candle is None:  # 如果还没有当前 K 线
            self.current_candle = [candle_ts, price, price, price, price, quantity]  # 创建第一根秒线
            return False  # 第一根还没闭合，暂不产生新闭合 K 线

        current_ts = int(self.current_candle[0])  # 取正在形成的 K 线时间戳
        if candle_ts == current_ts:  # 如果成交仍在同一秒内
            self.current_candle[2] = max(self.current_candle[2], price)  # 更新最高价
            self.current_candle[3] = min(self.current_candle[3], price)  # 更新最低价
            self.current_candle[4] = price  # 更新收盘价
            self.current_candle[5] += quantity  # 累加成交量
            return False  # 同一秒内还没有闭合新 K 线

        if candle_ts < current_ts:  # 如果收到乱序旧成交
            return False  # 忽略旧成交，避免破坏当前秒线

        self._close_current_candle()  # 秒数前进时，先闭合当前 K 线
        self._fill_empty_seconds(current_ts + 1000, candle_ts)  # 用上一收盘价填补中间无成交秒
        self.current_candle = [candle_ts, price, price, price, price, quantity]  # 开启新的当前秒 K 线
        return True  # 返回 True 表示刚产生了至少一根闭合 K 线

    def _close_current_candle(self) -> None:  # 定义函数：闭合当前 K 线
        if self.current_candle is None:  # 如果当前 K 线为空
            return  # 直接返回
        self.closed_candles.append(self.current_candle)  # 把当前 K 线加入闭合队列
        self.last_close_price = float(self.current_candle[4])  # 保存上一根闭合 K 线收盘价

    def _fill_empty_seconds(self, start_ts: int, end_ts: int) -> None:  # 定义函数：填补没有成交的空白秒
        if self.last_close_price is None:  # 如果还没有上一收盘价
            return  # 无法填补，直接返回
        ts = start_ts  # 从当前秒之后的第一秒开始填补
        while ts < end_ts:  # 一直填补到新成交所在秒之前
            price = self.last_close_price  # 使用上一收盘价作为 OHLC
            self.closed_candles.append([ts, price, price, price, price, 0.0])  # 添加一根无成交平盘秒线
            ts += 1000  # 前进到下一秒

    def closed(self) -> list[list[float]]:  # 定义函数：返回闭合 K 线列表
        return list(self.closed_candles)  # 把 deque 转成普通列表


async def iter_one_second_candles(symbol: str) -> AsyncIterator[list[list[float]]]:  # 定义异步生成器：持续产出闭合秒线
    aggregator = WebSocketOneSecondCandles(symbol)  # 创建秒线聚合器

    while True:  # 外层循环用于断线重连
        try:  # 尝试建立 WebSocket 连接
            print(f"[WS] connecting {aggregator.url}")  # 打印连接地址
            async with websockets.connect(aggregator.url, ping_interval=20, ping_timeout=20) as websocket:  # 建立 WebSocket 连接
                print("[WS] connected")  # 打印连接成功
                while True:  # 持续接收 WebSocket 消息
                    try:  # 尝试在指定时间内接收一条消息
                        message = await asyncio.wait_for(websocket.recv(), timeout=IDLE_TIMEOUT_SECONDS)  # 接收 WebSocket 消息
                    except TimeoutError:  # 如果长时间没有成交消息
                        print(f"[WS] no aggTrade message for {IDLE_TIMEOUT_SECONDS}s; waiting for trades")  # 打印空闲提示
                        continue  # 继续等待后续成交
                    data = json.loads(message)  # 解析 JSON 消息
                    price = float(data["p"])  # aggTrade 字段 p 是成交价
                    quantity = float(data["q"])  # aggTrade 字段 q 是成交数量
                    trade_time_ms = int(data["T"])  # aggTrade 字段 T 是成交时间
                    has_closed_candle = aggregator.update_with_trade(price, quantity, trade_time_ms)  # 更新秒线
                    if has_closed_candle:  # 如果产生了新闭合 K 线
                        yield aggregator.closed()  # 产出闭合 K 线列表
        except Exception as exc:  # 捕获连接断开、网络错误或解析异常
            print(f"[WS] disconnected: {exc}; reconnecting in 3 seconds")  # 打印断线原因
            await asyncio.sleep(3)  # 等待 3 秒后重连
