from risk.position import Position  # 导入持仓数据结构


def calculate_pnl(position: Position, exit_price: float) -> tuple[float, float]:  # 定义函数：计算平仓盈亏
    if position.entry_price <= 0:  # 如果开仓价无效，直接返回 0，避免除以 0 或污染权益曲线
        return 0.0, 0.0  # 无效持仓不参与盈亏计算

    if position.side == "long":  # 如果是多单
        pnl_usdt = (exit_price - position.entry_price) * position.amount  # 多单盈亏 = 价格上涨金额 * BTC 数量
        pnl_pct = (exit_price - position.entry_price) / position.entry_price  # 多单收益率 = 当前价相对开仓价的涨跌幅
    else:  # 如果是空单
        pnl_usdt = (position.entry_price - exit_price) * position.amount  # 空单盈亏 = 价格下跌金额 * BTC 数量
        pnl_pct = (position.entry_price - exit_price) / position.entry_price  # 空单收益率 = 开仓价相对当前价的下跌幅

    return pnl_usdt, pnl_pct  # 返回 USDT 盈亏和本笔交易收益率
