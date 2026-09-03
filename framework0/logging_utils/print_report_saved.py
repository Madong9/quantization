from pathlib import Path  # 用 pathlib 表示文件路径


def print_report_saved(csv_path: Path, png_path: Path | None) -> None:  # 定义函数：打印报告保存位置
    if png_path is None:  # 如果图片没有生成
        print(f"[REPORT] trade_csv={csv_path}")  # 只打印 CSV 路径
    else:  # 如果图片生成成功
        print(f"[REPORT] trade_csv={csv_path} equity_curve={png_path}")  # 同时打印 CSV 和曲线图路径
