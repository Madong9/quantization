from typing import Optional  # 表示函数可能返回字符串，也可能返回 None

from risk.position import Position  # 导入持仓数据结构


def should_close_position(position: Position, price: float) -> Optional[str]:  # 定义函数：判断是否触发止盈止损
    if position.side == "long":  # 如果当前是多单
        if price <= position.stop_loss:  # 多单当前价格跌到或跌破止损价
            return "stop_loss"  # 返回止损平仓原因
        if price >= position.take_profit:  # 多单当前价格涨到或涨破止盈价
            return "take_profit"  # 返回止盈平仓原因
    else:  # 如果当前不是多单，则视为空单
        if price >= position.stop_loss:  # 空单当前价格涨到或涨破止损价
            return "stop_loss"  # 返回止损平仓原因
        if price <= position.take_profit:  # 空单当前价格跌到或跌破止盈价
            return "take_profit"  # 返回止盈平仓原因

    return None  # 没有触发止盈止损时，返回 None
