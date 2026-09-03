from risk.account import Account  # 导入账户收益数据结构


def print_account_status(account: Account) -> None:  # 定义函数：打印模拟账户收益状态
    print(  # 开始打印账户日志
        "[ACCOUNT] "  # 日志前缀，表示账户状态
        f"balance={account.balance:.2f} USDT "  # 打印当前账户余额
        f"realized_pnl={account.realized_pnl:.2f} USDT "  # 打印累计已实现盈亏
        f"fees_paid={account.fees_paid:.2f} USDT "  # 打印累计手续费
        f"return={account.return_pct * 100:.2f}%"  # 打印账户累计收益率
    )  # 账户日志打印结束
