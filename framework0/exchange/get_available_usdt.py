import os  # 读取模拟账户余额环境变量

import ccxt  # 使用 ccxt 的异常类型和 Binance 类型

from config import PAPER_TRADING  # 导入交易模式，用于区分模拟和实盘余额处理


def get_available_usdt(exchange: ccxt.binance) -> float:  # 定义函数：获取合约账户可用 USDT
    try:  # 开始尝试读取真实账户余额
        balance = exchange.fetch_balance({"type": "future"})  # 读取 Binance 合约账户余额
        info = balance.get("info", {})  # 取原始 futures 账户信息
        available_balance = info.get("availableBalance")  # 优先使用 futures 账户的可用余额
        if available_balance is not None:  # 如果成功拿到了可用 USDT
            return float(available_balance)  # 转成 float 并返回
        free_usdt = balance.get("USDT", {}).get("free")  # 兼容 ccxt 映射到的 USDT 可用余额
        if free_usdt is not None:  # 如果成功拿到了可用 USDT
            return float(free_usdt)  # 转成 float 并返回
    except ccxt.AuthenticationError as exc:  # 捕获 API key 缺失、错误或权限不足等认证异常
        if not PAPER_TRADING:  # 如果当前是实盘模式
            raise RuntimeError(f"Could not authenticate futures account in LIVE mode: {exc}") from exc  # 实盘认证失败必须停止
        print("[WARN] API key not configured or invalid; using simulated balance.")  # 模拟模式打印警告并切换模拟余额
    except ccxt.BaseError as exc:  # 捕获 ccxt 抛出的其他交易所相关异常
        if not PAPER_TRADING:  # 如果当前是实盘模式
            raise RuntimeError(f"Could not fetch futures balance in LIVE mode: {exc}") from exc  # 实盘余额读取失败必须停止
        print(f"[WARN] Could not fetch futures balance: {exc}; using simulated balance.")  # 模拟模式打印异常原因

    if not PAPER_TRADING:  # 如果当前是实盘模式但没有拿到 USDT free 字段
        raise RuntimeError("Could not read USDT free balance in LIVE mode.")  # 阻止使用模拟余额继续实盘
    return float(os.getenv("PAPER_USDT_BALANCE", "1000"))  # 无法读取真实余额时，使用环境变量或默认 1000 USDT
