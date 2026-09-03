import os  # 读取环境变量，用来确认是否允许真实下单。

from config import ALLOW_HIGH_LEVERAGE_ENV, LEVERAGE, LIVE_TRADING_CONFIRM_VALUE, LIVE_TRADING_ENV, MAX_LIVE_LEVERAGE, PAPER_TRADING  # 导入实盘安全配置。


def ensure_live_trading_allowed() -> None:  # 定义函数：启动实盘前做强制安全检查。
    if PAPER_TRADING:  # 如果仍然是模拟交易模式。
        return  # 模拟模式不需要真实下单确认。

    live_confirm = os.getenv(LIVE_TRADING_ENV, "")  # 读取用户是否明确允许实盘的环境变量。
    if live_confirm != LIVE_TRADING_CONFIRM_VALUE:  # 如果确认值不完全匹配。
        raise RuntimeError(  # 抛出错误，阻止程序进入真实下单。
            f"Refusing LIVE trading. Set {LIVE_TRADING_ENV}={LIVE_TRADING_CONFIRM_VALUE} to enable real orders."  # 告诉用户需要设置的确认变量。
        )  # 安全错误构造结束。

    if not os.getenv("BINANCE_API_KEY") or not os.getenv("BINANCE_API_SECRET"):  # 如果没有提供 Binance API key 或 secret。
        raise RuntimeError("Refusing LIVE trading. BINANCE_API_KEY and BINANCE_API_SECRET are required.")  # 阻止无密钥实盘启动。

    if LEVERAGE > MAX_LIVE_LEVERAGE and os.getenv(ALLOW_HIGH_LEVERAGE_ENV, "") != "true":  # 如果杠杆超过默认实盘上限且没有额外确认。
        raise RuntimeError(  # 抛出错误，避免误用过高杠杆。
            f"Refusing LIVE trading with leverage={LEVERAGE}. Set {ALLOW_HIGH_LEVERAGE_ENV}=true to override."  # 提示如何显式覆盖高杠杆限制。
        )  # 高杠杆错误构造结束。
