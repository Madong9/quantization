from risk.account import Account  # 导入账户收益数据结构
from risk.position import Position  # 导入持仓数据结构
from utils.utc_now import utc_now  # 导入 UTC 当前时间函数


def print_position_close(  # 定义函数：打印平仓信息
    position: Position,  # 传入当前持仓
    price: float,  # 传入平仓价格
    reason: str,  # 传入平仓原因
    gross_pnl_usdt: float,  # 传入本笔交易毛盈亏
    exit_fee_usdt: float,  # 传入本笔交易平仓手续费
    realized_pnl_usdt: float,  # 传入本笔交易成交后的已实现盈亏
    pnl_pct: float,  # 传入本笔交易收益率
    account: Account,  # 传入更新后的账户对象
    mode: str = "PAPER",  # 传入运行模式，PAPER 表示模拟，LIVE 表示实盘
) -> None:
    realized_return_pct = (realized_pnl_usdt / position.margin_usdt * 100) if position.margin_usdt else (pnl_pct * 100)  # 按保证金口径计算单笔已实现收益率
    print(  # 开始打印平仓日志
        f"[{mode} CLOSE] "  # 日志前缀，表示模拟或实盘平仓
        f"{position.side.upper()} reason={reason} exit={price:.2f} "  # 打印方向、平仓原因和平仓价
        f"gross_pnl={gross_pnl_usdt:.2f} USDT fee={position.entry_fee_usdt + exit_fee_usdt:.2f} USDT "  # 打印总手续费
        f"realized_pnl={realized_pnl_usdt:.2f} USDT trade_return={realized_return_pct:.2f}% "  # 打印本笔交易成交后的已实现盈亏
        f"balance={account.balance:.2f} USDT account_return={account.return_pct * 100:.2f}% "  # 打印账户余额和账户收益
        f"time={utc_now().isoformat()}"  # 打印平仓时间（北京时间）
    )  # 平仓日志打印结束
