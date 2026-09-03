from __future__ import annotations  # 允许使用更现代的类型注解写法

import csv  # 用 CSV 文件保存每笔交易记录
from pathlib import Path  # 用 pathlib 处理文件夹和文件路径

from config import TRADE_HISTORY_CSV  # 导入交易记录文件名
from risk.account import Account  # 导入账户收益数据结构
from risk.position import Position  # 导入持仓数据结构
from utils.utc_now import utc_now  # 导入 UTC 当前时间函数


CSV_FIELDS = [  # 定义 CSV 表头字段
    "trade_id",  # 交易编号
    "closed_at_bj",  # 平仓时间
    "side",  # 持仓方向
    "reason",  # 平仓原因
    "entry_price",  # 开仓价
    "exit_price",  # 平仓价
    "amount",  # 标的币数量
    "leverage",  # 杠杆倍数
    "margin_usdt",  # 本次使用保证金
    "notional_usdt",  # 杠杆放大后的名义仓位
    "balance_before",  # 本次交易平仓前账户余额
    "gross_pnl_usdt",  # 本次交易毛盈亏
    "entry_fee_usdt",  # 本次交易开仓手续费
    "exit_fee_usdt",  # 本次交易平仓手续费
    "total_fee_usdt",  # 本次交易总手续费
    "realized_pnl_usdt",  # 本次交易成交后的已实现盈亏
    "balance_after",  # 本次交易平仓后账户余额
    "account_return_pct",  # 当前账户累计收益率
]  # CSV 表头字段结束


def record_trade(  # 定义函数：把每次交易前后余额写入 CSV
    trade_id: int,  # 交易编号
    position: Position,  # 当前平掉的持仓
    exit_price: float,  # 平仓价格
    reason: str,  # 平仓原因
    balance_before: float,  # 平仓前账户余额
    gross_pnl_usdt: float,  # 本次交易毛盈亏
    exit_fee_usdt: float,  # 本次交易平仓手续费
    account: Account,  # 已经更新后的账户对象
    report_dir: Path,  # 本次运行的报告目录
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)  # 确保报告目录存在
    csv_path = report_dir / TRADE_HISTORY_CSV  # 拼出 CSV 文件完整路径
    file_exists = csv_path.exists()  # 判断 CSV 文件是否已经存在

    with csv_path.open("a", newline="", encoding="utf-8") as file:  # 以追加模式打开 CSV
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)  # 创建字典写入器
        if not file_exists:  # 如果文件是第一次创建
            writer.writeheader()  # 先写入 CSV 表头
        writer.writerow(  # 写入一笔交易记录
            {  # 交易记录字典开始
                "trade_id": trade_id,  # 写入交易编号
                "closed_at_bj": utc_now().isoformat(),  # 写入平仓时间
                "side": position.side,  # 写入持仓方向
                "reason": reason,  # 写入平仓原因
                "entry_price": f"{position.entry_price:.8f}",  # 写入开仓价
                "exit_price": f"{exit_price:.8f}",  # 写入平仓价
                "amount": f"{position.amount:.8f}",  # 写入标的币数量
                "leverage": position.leverage,  # 写入杠杆倍数
                "margin_usdt": f"{position.margin_usdt:.8f}",  # 写入本次使用保证金
                "notional_usdt": f"{position.notional_usdt:.8f}",  # 写入名义仓位
                "balance_before": f"{balance_before:.8f}",  # 写入平仓前余额
                "gross_pnl_usdt": f"{gross_pnl_usdt:.8f}",  # 写入本次毛盈亏
                "entry_fee_usdt": f"{position.entry_fee_usdt:.8f}",  # 写入本次开仓手续费
                "exit_fee_usdt": f"{exit_fee_usdt:.8f}",  # 写入本次平仓手续费
                "total_fee_usdt": f"{position.entry_fee_usdt + exit_fee_usdt:.8f}",  # 写入本次总手续费
                "realized_pnl_usdt": f"{gross_pnl_usdt - position.entry_fee_usdt - exit_fee_usdt:.8f}",  # 写入本次成交后的已实现盈亏
                "balance_after": f"{account.balance:.8f}",  # 写入平仓后余额
                "account_return_pct": f"{account.return_pct * 100:.8f}",  # 写入账户累计收益率
            }  # 交易记录字典结束
        )  # 写入一行交易记录结束

    return csv_path  # 返回 CSV 文件路径
