from __future__ import annotations  # 启用延迟解析类型注解，兼容较新的类型写法。
from datetime import datetime  # 导入 datetime，用于 leverage 回调的当前时间参数类型。
from typing import Optional  # 导入 Optional，用于表示 entry_tag 可能为空。
from pandas import DataFrame  # 导入 pandas DataFrame，Freqtrade 会把 K 线数据传成这个结构。
from freqtrade.strategy import IStrategy  # 导入 Freqtrade 策略基类，所有策略都需要继承它。


class EmaCrossFuturesStrategy(IStrategy):  # 定义 EMA 交叉合约策略类，Freqtrade 会实例化这个类。
    """ETH/USDT Binance futures EMA crossover strategy."""  # 说明这个策略用于 Binance 合约 EMA 交叉。

    INTERFACE_VERSION = 3  # 使用 Freqtrade v3 策略接口，支持多空方向等新接口。
    can_short = True  # 允许策略做空，适配 Binance USDT 本位合约。
    timeframe = "1m"  # 设置策略 K 线周期为 1 分钟。
    startup_candle_count = 35  # 启动时至少准备 35 根 K 线，确保慢 EMA 有足够历史数据。
    process_only_new_candles = True  # 只在新 K 线出现时重新计算策略，减少重复计算。
    fast_ema_period = 12  # 设置快线 EMA 周期为 12。
    slow_ema_period = 36  # 设置慢线 EMA 周期为 36。
    leverage_value = 10.0  # 设置策略希望使用的杠杆倍数为 10 倍。
    minimal_roi = {  # 设置最小止盈 ROI，Freqtrade 会用这个表判断是否满足收益退出。
        "0": 0.20  # 从开仓开始就允许达到 20% 杠杆后收益时止盈。
    }  # 结束 minimal_roi 配置字典。
    stoploss = -0.30  # 设置最大止损为 -30% 杠杆后收益。
    trailing_stop = False  # 关闭移动止损，避免止损价随盈利自动上移。
    use_exit_signal = False  # 关闭策略退出信号，只保留 ROI 止盈和止损离场。
    exit_profit_only = False  # 不限制只有盈利时才能根据信号退出。
    ignore_roi_if_entry_signal = False  # 即使入场信号仍存在，也不忽略 ROI 退出规则。

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:  # 计算策略指标并返回带指标的数据表。
        dataframe["ema_fast"] = dataframe["close"].ewm(  # 基于收盘价计算快 EMA，并保存到 ema_fast 列。
            span=self.fast_ema_period,  # 使用 fast_ema_period 指定快 EMA 的周期。
            adjust=False,  # 使用递推 EMA 算法，更贴近交易软件常见 EMA。
        ).mean()  # 生成快 EMA 序列。
        dataframe["ema_slow"] = dataframe["close"].ewm(  # 基于收盘价计算慢 EMA，并保存到 ema_slow 列。
            span=self.slow_ema_period,  # 使用 slow_ema_period 指定慢 EMA 的周期。
            adjust=False,  # 使用递推 EMA 算法，和快 EMA 保持一致。
        ).mean()  # 生成慢 EMA 序列。
        return dataframe  # 返回已经添加 EMA 指标的数据表。

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:  # 计算入场信号并返回数据表。
        crossed_above = (  # 判断快 EMA 是否刚刚上穿慢 EMA。
            (dataframe["ema_fast"] > dataframe["ema_slow"])  # 当前 K 线快 EMA 高于慢 EMA。
            & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))  # 上一根 K 线快 EMA 小于等于慢 EMA。
        )  # 完成上穿条件计算。
        crossed_below = (  # 判断快 EMA 是否刚刚下穿慢 EMA。
            (dataframe["ema_fast"] < dataframe["ema_slow"])  # 当前 K 线快 EMA 低于慢 EMA。
            & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))  # 上一根 K 线快 EMA 大于等于慢 EMA。
        )  # 完成下穿条件计算。
        dataframe.loc[  # 给满足做多条件的 K 线写入 Freqtrade 入场字段。
            crossed_above & (dataframe["volume"] > 0),  # 要求 EMA 上穿且成交量大于 0。
            ["enter_long", "enter_tag"],  # 设置做多入场标记和入场标签两列。
        ] = (1, "ema12_cross_above_ema36")  # 标记做多入场，并写入便于日志识别的标签。
        dataframe.loc[  # 给满足做空条件的 K 线写入 Freqtrade 入场字段。
            crossed_below & (dataframe["volume"] > 0),  # 要求 EMA 下穿且成交量大于 0。
            ["enter_short", "enter_tag"],  # 设置做空入场标记和入场标签两列。
        ] = (1, "ema12_cross_below_ema36")  # 标记做空入场，并写入便于日志识别的标签。
        return dataframe  # 返回已经添加入场信号的数据表。

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:  # 保留方法签名，但不生成任何退出信号。
        return dataframe  # 退出只交给 ROI 和 stoploss。

    def leverage(  # 定义 Freqtrade 杠杆回调，开仓前由框架调用。
        self,  # 当前策略实例。
        pair: str,  # 当前交易对，例如 ETH/USDT:USDT。
        current_time: datetime,  # 当前回调时间。
        current_rate: float,  # 当前市场价格。
        proposed_leverage: float,  # Freqtrade 或交易所建议的杠杆。
        max_leverage: float,  # 交易所允许的最大杠杆。
        entry_tag: Optional[str],  # 入场标签，可能为空。
        side: str,  # 交易方向，通常是 long 或 short。
        **kwargs,  # 接收 Freqtrade 未来可能传入的额外参数。
    ) -> float:  # 返回最终要使用的杠杆倍数。
        return min(self.leverage_value, max_leverage)  # 使用策略设定杠杆，但不超过交易所上限。
