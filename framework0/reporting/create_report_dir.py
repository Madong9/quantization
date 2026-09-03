from pathlib import Path  # 用 pathlib 处理目录路径

from config import REPORT_DIR  # 导入报告根目录
from utils.utc_now import utc_now  # 导入 UTC 当前时间函数


def create_report_dir() -> Path:  # 定义函数：为本次运行创建独立报告目录
    run_name = utc_now().strftime("run_%Y%m%d_%H%M%S_bj")  # 用北京时间生成本次运行目录名
    report_dir = Path(REPORT_DIR) / run_name  # 拼出本次运行的报告目录
    report_dir.mkdir(parents=True, exist_ok=True)  # 创建目录，父目录不存在时也一并创建
    return report_dir  # 返回本次运行报告目录
