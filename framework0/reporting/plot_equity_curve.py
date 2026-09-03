from __future__ import annotations  # 允许使用更现代的类型注解写法

import csv  # 读取交易记录 CSV
from pathlib import Path  # 用 pathlib 处理文件路径

from config import EQUITY_CURVE_PNG, TRADE_HISTORY_CSV  # 导入报告文件配置


def plot_equity_curve(initial_balance: float, report_dir: Path) -> Path | None:  # 定义函数：根据交易记录生成账户余额曲线
    try:  # 尝试导入 matplotlib
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]  # 导入画图库
    except ImportError:  # 如果没有安装 matplotlib
        print("[WARN] matplotlib not installed; skipped equity curve image.")  # 打印提示，但不影响交易记录
        return None  # 返回 None 表示没有生成图片

    csv_path = report_dir / TRADE_HISTORY_CSV  # 拼出交易记录 CSV 路径
    png_path = report_dir / EQUITY_CURVE_PNG  # 拼出收益曲线图片路径

    balances = [initial_balance]  # 曲线从初始余额开始
    trade_numbers = [0]  # 第 0 个点表示还没有平仓交易

    if csv_path.exists():  # 如果交易记录文件存在
        with csv_path.open("r", newline="", encoding="utf-8") as file:  # 打开交易记录 CSV
            reader = csv.DictReader(file)  # 创建字典读取器
            for row in reader:  # 遍历每一笔交易记录
                trade_numbers.append(int(row["trade_id"]))  # 添加交易编号作为横坐标
                balances.append(float(row["balance_after"]))  # 添加平仓后余额作为纵坐标

    plt.figure(figsize=(10, 5))  # 创建画布并设置尺寸
    plt.plot(trade_numbers, balances, marker="o", linewidth=2)  # 绘制账户余额曲线
    plt.title("Paper Trading Equity Curve")  # 设置图表标题
    plt.xlabel("Closed Trade Number")  # 设置横轴名称
    plt.ylabel("Balance (USDT)")  # 设置纵轴名称
    plt.grid(True, alpha=0.3)  # 显示浅色网格，方便观察曲线
    plt.tight_layout()  # 自动调整边距
    plt.savefig(png_path, dpi=150)  # 保存图片到报告目录
    plt.close()  # 关闭画布，避免长期运行时占用内存

    return png_path  # 返回图片路径
