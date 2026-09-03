from __future__ import annotations  # 延迟解析类型注解，提升兼容性。

import ccxt  # 导入 ccxt 类型，方便标注交易所对象。

from config import SYMBOL  # 导入交易对配置。
from risk.position import Position  # 导入持仓数据结构。


def close_live_position(exchange: ccxt.binance, position: Position, reason: str) -> dict:  # 定义函数：用 reduceOnly 市价单平真实合约仓位。
    side = "sell" if position.side == "long" else "buy"  # 平多用 sell，平空用 buy。
    position_side = "LONG" if position.side == "long" else "SHORT"  # 双向持仓模式下必须显式指定持仓方向。
    amount = float(exchange.amount_to_precision(SYMBOL, position.amount))  # 按交易所精度格式化平仓数量。
    if amount <= 0:  # 如果精度处理后数量无效。
        raise RuntimeError(f"Refusing to close LIVE position with invalid amount={amount}")  # 阻止发送无效订单。

    order = exchange.create_order(  # 调用 Binance 合约市价单接口。
        SYMBOL,  # 指定交易对。
        "market",  # 使用市价单尽快平仓。
        side,  # 指定平仓方向。
        amount,  # 指定平仓数量。
        None,  # 市价单不需要限价价格。
        {"positionSide": position_side},  # 双向持仓模式下只需要显式指定持仓方向。
    )  # 下单调用结束。
    print(f"[LIVE CLOSE] side={position.side.upper()} amount={amount} reason={reason} order_id={order.get('id')}")  # 打印实盘平仓订单日志。
    return order  # 返回交易所订单响应，便于后续扩展记录。
