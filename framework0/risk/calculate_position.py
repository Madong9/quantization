from config import LEVERAGE, POSITION_FRACTION, STOP_LOSS_PCT, TAKE_PROFIT_PCT  # 导入仓位、杠杆和风控参数
from risk.position import Position  # 导入持仓数据结构
from utils.utc_now import utc_now  # 导入 UTC 当前时间函数


def calculate_position(signal: str, price: float, available_usdt: float) -> Position:  # 定义函数：根据信号计算模拟持仓
    margin = available_usdt * POSITION_FRACTION  # 用可用 USDT 的 20% 作为本次交易保证金
    notional = margin * LEVERAGE  # 用杠杆放大保证金，得到本次交易名义金额
    amount = notional / price  # 用名义金额除以价格，得到标的币数量

    if signal == "buy":  # 如果信号是买入，表示开多
        stop_loss = price * (1 - STOP_LOSS_PCT/LEVERAGE)  # 多单止损价为入场价下方 1%
        take_profit = price * (1 + TAKE_PROFIT_PCT/LEVERAGE)  # 多单止盈价为入场价上方 1%
    else:  # 否则信号是卖出，表示开空
        stop_loss = price * (1 + STOP_LOSS_PCT/LEVERAGE)  # 空单止损价为入场价上方 1%
        take_profit = price * (1 - TAKE_PROFIT_PCT/LEVERAGE)  # 空单止盈价为入场价下方 1%

    return Position(  # 创建并返回一个模拟持仓对象
        side="long" if signal == "buy" else "short",  # 根据信号设置方向：buy 为 long，sell 为 short
        entry_price=price,  # 记录开仓价
        amount=amount,  # 记录开仓数量
        margin_usdt=margin,  # 记录本次使用的保证金
        notional_usdt=notional,  # 记录杠杆放大后的名义仓位
        leverage=LEVERAGE,  # 记录杠杆倍数
        stop_loss=stop_loss,  # 记录止损价
        take_profit=take_profit,  # 记录止盈价
        opened_at=utc_now(),  # 记录开仓时间
    )  # 持仓对象创建结束
