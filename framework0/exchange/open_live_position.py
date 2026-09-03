from __future__ import annotations  # 延迟解析类型注解，提升兼容性。

import ccxt  # 导入 ccxt 类型，方便标注交易所对象。

from config import SYMBOL  # 导入交易对配置。
from risk.position import Position  # 导入持仓数据结构。


def _clear_symbol_open_orders(exchange: ccxt.binance) -> None:  # 定义函数：清理该交易对残留的未成交订单。
    try:  # 尝试撤掉该交易对的所有未成交订单。
        exchange.cancel_all_orders(SYMBOL, {"type": "future"})  # 撤销该交易对的 futures 挂单与条件单。
    except ccxt.BaseError as exc:  # 捕获撤单异常。
        message = str(exc)  # 转成字符串用于判断是否可忽略。
        if "No open orders" in message or "Unknown order" in message or "Order does not exist" in message:  # 没有残单时忽略。
            return  # 直接返回。
        raise  # 其他异常继续抛出。


def _fetch_open_algo_orders(exchange: ccxt.binance) -> list[dict]:  # 定义函数：读取该交易对当前打开的条件单。
    response = exchange.fapiPrivateGetOpenAlgoOrders({"symbol": exchange.market(SYMBOL)["id"]})  # 拉取 futures open algo orders。
    return response if isinstance(response, list) else response.get("data", response)  # 兼容不同 ccxt/接口返回结构。

    try:  # 再撤掉该交易对残留的 algo 条件单，例如 TP/SL。
        exchange.fapiPrivateDeleteAlgoOpenOrders({"symbol": exchange.market(SYMBOL)["id"]})  # 清除 open algo orders。
    except ccxt.BaseError as exc:  # 捕获 algo 撤单异常。
        message = str(exc)  # 转成字符串用于判断是否可忽略。
        if "No open orders" in message or "Unknown order" in message or "Order does not exist" in message:  # 没有残单时忽略。
            return  # 直接返回。
        raise  # 其他异常继续抛出。


def open_live_position(exchange: ccxt.binance, position: Position) -> dict:  # 定义函数：用市价单开真实合约仓位。
    side = "buy" if position.side == "long" else "sell"  # 多单用 buy 开仓，空单用 sell 开仓。
    position_side = "LONG" if position.side == "long" else "SHORT"  # 双向持仓模式下必须显式指定持仓方向。
    amount = float(exchange.amount_to_precision(SYMBOL, position.amount))  # 按交易所精度格式化下单数量。
    if amount <= 0:  # 如果精度处理后数量无效。
        raise RuntimeError(f"Refusing to open LIVE position with invalid amount={amount}")  # 阻止发送无效订单。

    entry_order = exchange.create_order(  # 调用 Binance 合约市价单接口。
        SYMBOL,  # 指定交易对。
        "market",  # 使用市价单立即成交。
        side,  # 指定买入或卖出方向。
        amount,  # 指定开仓数量。
        None,  # 市价单不需要限价价格。
        {"positionSide": position_side},  # 双向持仓模式下只需要显式指定持仓方向。
    )  # 下单调用结束。

    exit_side = "sell" if position.side == "long" else "buy"  # 多单平仓用 sell，空单平仓用 buy。

    stop_order = None  # 初始化止损单响应。
    take_profit_order = None  # 初始化止盈单响应。
    for attempt in range(2):  # 最多尝试两次挂保护单。
        try:  # 尝试挂出止损单和止盈单。
            _clear_symbol_open_orders(exchange)  # 先清理该交易对已有的残留挂单。
            stop_order = exchange.create_order(  # 挂出止损单。
                SYMBOL,  # 指定交易对。
                "STOP_MARKET",  # Binance 合约止损市价单。
                exit_side,  # 按仓位方向的反向下单。
                amount,  # 维持与持仓相同的数量。
                None,  # 市价止损不需要限价。
                {  # Binance 原生保护单参数。
                    "stopPrice": position.stop_loss,  # 止损触发价。
                    "closePosition": True,  # 触发后直接平掉整个仓位。
                    "positionSide": position_side,  # 绑定当前持仓方向。
                    "workingType": "MARK_PRICE",  # 使用标记价格触发，减少插针影响。
                },
            )  # 止损单挂单结束。
            take_profit_order = exchange.create_order(  # 挂出止盈单。
                SYMBOL,  # 指定交易对。
                "TAKE_PROFIT_MARKET",  # Binance 合约止盈市价单。
                exit_side,  # 按仓位方向的反向下单。
                amount,  # 维持与持仓相同的数量。
                None,  # 市价止盈不需要限价。
                {  # Binance 原生保护单参数。
                    "stopPrice": position.take_profit,  # 止盈触发价。
                    "closePosition": True,  # 触发后直接平掉整个仓位。
                    "positionSide": position_side,  # 绑定当前持仓方向。
                    "workingType": "MARK_PRICE",  # 使用标记价格触发，减少插针影响。
                },
            )  # 止盈单挂单结束。
            break  # 两单都成功后退出重试循环。
        except ccxt.ExchangeError as exc:  # 捕获创建保护单时的交易所错误。
            message = str(exc)  # 转成字符串用于判断具体错误。
            if "-4130" in message and attempt == 0:  # 如果是重复的 GTE/closePosition 条件单冲突，就清理后重试一次。
                _clear_symbol_open_orders(exchange)  # 再清一遍该交易对残单。
                continue  # 进入第二次重试。
            raise  # 其他错误或第二次失败直接抛出。
    print(  # 打印实盘开仓和保护单日志。
        f"[LIVE OPEN] side={position.side.upper()} amount={amount} "
        f"entry_order_id={entry_order.get('id')} stop_order_id={stop_order.get('id')} tp_order_id={take_profit_order.get('id')}"
    )
    try:  # 再次读取并打印当前打开的条件单，便于在 testnet 中核对 10% 止盈止损是否已挂上。
        open_algo_orders = _fetch_open_algo_orders(exchange)  # 获取当前 open algo orders。
        print(  # 打印条件单核验结果。
            f"[LIVE PROTECT] open_algo_orders={len(open_algo_orders)} "
            f"symbol={SYMBOL} stop={position.stop_loss:.2f} tp={position.take_profit:.2f}"
        )
    except ccxt.BaseError as exc:  # 如果读取条件单失败，只打印提示，不影响交易流程。
        print(f"[LIVE PROTECT] could not verify open algo orders: {exc}")  # 打印核验失败提示。
    return {"entry": entry_order, "stop_loss": stop_order, "take_profit": take_profit_order}  # 返回所有订单响应。
