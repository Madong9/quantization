from pathlib import Path  # 用 pathlib 表示返回的文件路径

from reporting.plot_equity_curve import plot_equity_curve  # 导入账户余额曲线生成函数
from reporting.record_trade import record_trade  # 导入交易记录写入函数
from risk.account import Account  # 导入账户收益数据结构
from risk.position import Position  # 导入持仓数据结构


def save_trade_report(  # 定义函数：保存交易记录并更新收益曲线
    trade_id: int,  # 交易编号
    position: Position,  # 当前平掉的持仓
    exit_price: float,  # 平仓价格
    reason: str,  # 平仓原因
    balance_before: float,  # 平仓前账户余额
    gross_pnl_usdt: float,  # 本次交易毛盈亏
    exit_fee_usdt: float,  # 本次交易平仓手续费
    account: Account,  # 已经更新后的账户对象
    report_dir: Path,  # 本次运行的报告目录
) -> tuple[Path, Path | None]:
    csv_path = record_trade(  # 先把交易前后余额写入 CSV
        trade_id=trade_id,  # 传入交易编号
        position=position,  # 传入平仓持仓
        exit_price=exit_price,  # 传入平仓价格
        reason=reason,  # 传入平仓原因
        balance_before=balance_before,  # 传入平仓前余额
        gross_pnl_usdt=gross_pnl_usdt,  # 传入本次毛盈亏
        exit_fee_usdt=exit_fee_usdt,  # 传入本次平仓手续费
        account=account,  # 传入更新后的账户
        report_dir=report_dir,  # 传入本次运行报告目录
    )  # CSV 写入完成
    png_path = plot_equity_curve(account.initial_balance, report_dir)  # 再根据 CSV 更新账户余额曲线图片
    return csv_path, png_path  # 返回 CSV 和图片路径
