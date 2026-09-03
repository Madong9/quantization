import ccxt  # 导入 ccxt 交易所类型和异常类型

from config import FUTURES_TAKER_FEE_PCT  # 导入合约 taker 手续费配置


def get_futures_taker_fee_pct(exchange: ccxt.binance, symbol: str) -> float:  # 定义函数：从交易所读取合约 taker 手续费率
    try:  # 尝试从交易所获取真实费率
        trading_fee = exchange.fetch_trading_fee(symbol)  # 读取指定交易对的 maker/taker 手续费
        taker_fee_pct = float(trading_fee["taker"])  # 取 taker 手续费率
        if taker_fee_pct > 0:  # 如果读取到了有效费率
            return taker_fee_pct  # 直接返回交易所费率
    except Exception:  # 捕获交易所、权限或网络异常后回退到配置值
        pass  # 使用下方的配置默认值

    return FUTURES_TAKER_FEE_PCT  # 无法从交易所读取时回退到配置中的估算费率


def estimate_futures_fee(notional_usdt: float, fee_pct: float = FUTURES_TAKER_FEE_PCT) -> float:  # 定义函数：估算合约手续费
    return abs(notional_usdt) * fee_pct  # 以名义仓位乘以手续费率估算开/平仓手续费