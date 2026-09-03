#!/usr/bin/env python3  # 使用系统环境中的 python3 来运行这个脚本
# Binance USDT 本位合约 EMA 均线交叉模拟交易脚本入口。  # 说明脚本用途

from run import run  # 从单独的 run.py 文件导入主运行函数


if __name__ == "__main__":  # 当这个文件被直接运行时，执行下面的入口逻辑
    run()  # 启动交易主循环
