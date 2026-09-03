from __future__ import annotations  # 延迟解析类型注解，提升兼容性

from dataclasses import dataclass  # 用 dataclass 简化持仓数据结构
from datetime import datetime  # 用于标记开仓时间


@dataclass  # 自动生成初始化方法，方便保存持仓字段
class Position:  # 定义一个持仓对象，用来记录模拟交易状态
    side: str  # 持仓方向，long 表示做多，short 表示做空
    entry_price: float  # 开仓价格
    amount: float  # 持仓数量，单位是交易标的币
    margin_usdt: float  # 本次使用的保证金，单位 USDT
    notional_usdt: float  # 杠杆放大后的名义仓位，单位 USDT
    leverage: int  # 杠杆倍数
    stop_loss: float  # 止损价格
    take_profit: float  # 止盈价格
    opened_at: datetime  # 开仓时间
    entry_fee_usdt: float = 0.0  # 开仓手续费，单位 USDT
