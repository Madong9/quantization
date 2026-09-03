from risk.position import Position  # 导入持仓数据结构


def print_position_open(position: Position, mode: str = "PAPER") -> None:  # 定义函数：打印开仓信息
    print(  # 开始打印开仓日志
        f"[{mode} OPEN] "  # 日志前缀，表示模拟或实盘开仓
        f"{position.side.upper()} leverage={position.leverage}x "  # 打印方向和杠杆倍数
        f"margin={position.margin_usdt:.2f} USDT notional={position.notional_usdt:.2f} USDT "  # 打印保证金和名义仓位
        f"amount={position.amount:.6f} "  # 打印持仓数量
        f"entry={position.entry_price:.2f} "  # 打印开仓价格，保留两位小数
        f"sl={position.stop_loss:.2f} tp={position.take_profit:.2f} "  # 打印止损价和止盈价
        f"time={position.opened_at.isoformat()}"  # 打印开仓时间
    )  # 开仓日志打印结束
