from __future__ import annotations  # 延迟解析类型注解，提升兼容性。

import ccxt  # 导入 ccxt，用于捕获交易所异常。

from config import LEVERAGE, MARGIN_MODE, SYMBOL  # 导入交易对、杠杆和保证金模式配置。


def configure_live_symbol(exchange: ccxt.binance) -> None:  # 定义函数：为实盘交易对设置合约参数。
    exchange.load_markets(False, {"type": "future"})  # 只加载 USDT 本位合约市场，避免拉取现货/margin 相关接口。
    margin_mode = MARGIN_MODE.lower()  # ccxt 的统一接口通常使用小写 isolated 或 cross。
    market_id = exchange.market(SYMBOL)["id"]  # 取 Binance 内部交易对 ID，供撤单接口使用。

    try:  # 先清理该交易对上残留的未成交订单，避免切换持仓模式失败。
        exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False  # 允许拉取全账户 futures 挂单，避免 ccxt 的告警中断启动。
        open_orders = exchange.fetch_open_orders(None, {"type": "future"})  # 拉取 futures 账户中的所有未成交订单。
        canceled_orders = 0  # 记录实际撤掉的订单数量。
        for order in open_orders:  # 遍历每一个残留订单。
            symbol = order.get("symbol")  # 取订单所属交易对。
            if not symbol:  # 如果缺少交易对信息。
                continue  # 跳过无效订单记录。
            exchange.cancel_order(order["id"], symbol, {"type": "future"})  # 逐个撤单，避免 position mode 切换被阻塞。
            canceled_orders += 1  # 更新撤单计数。
        if canceled_orders:  # 如果确实有订单被撤掉。
            print(f"[LIVE CONFIG] canceled_open_orders={canceled_orders} symbol={SYMBOL}")  # 打印清理结果。
        exchange.fapiPrivateDeleteAlgoOpenOrders({"symbol": market_id})  # 再清理 futures 条件单，避免 TP/SL 残留。
    except ccxt.AuthenticationError as exc:  # 如果只是预检接口认证失败，不阻塞启动。
        print(f"[LIVE CONFIG] skipped preflight order cleanup due to auth error: {exc}")  # 打印认证问题提示。
    except ccxt.BaseError as exc:  # 捕获撤单相关异常。
        message = str(exc)  # 转成字符串用于判断是否可忽略。
        if "No open orders" in message or "Order does not exist" in message or "Unknown order" in message:  # 没有残留订单时忽略。
            print(f"[LIVE CONFIG] no_open_orders_to_cancel symbol={SYMBOL}")  # 打印无残单提示。
        else:  # 其他异常继续抛出。
            raise  # 避免带着未知状态继续启动。

    for attempt in range(2):  # 最多尝试两次设置双向持仓模式。
        try:  # 尝试设置双向持仓模式。
            exchange.set_position_mode(True)  # 启用 hedge mode，允许 LONG/SHORT 分别持仓。
            print(f"[LIVE CONFIG] position_mode=HEDGE symbol={SYMBOL}")  # 打印持仓模式设置成功日志。
            break  # 设置成功后直接退出重试循环。
        except ccxt.AuthenticationError as exc:  # 如果只是认证失败，不阻塞启动。
            print(f"[LIVE CONFIG] skipped position_mode setup due to auth error: {exc}")  # 打印认证问题提示。
            break  # 继续后续启动流程。
        except ccxt.BaseError as exc:  # 捕获 ccxt 抛出的交易所异常。
            message = str(exc)  # 转成字符串用于判断是否只是“不需要修改”。
            if "No need to change position side" in message or "not modified" in message.lower():  # Binance 已经是双向持仓模式时会报类似提示。
                print(f"[LIVE CONFIG] position_mode already HEDGE symbol={SYMBOL}")  # 打印无需修改日志。
                break  # 目标状态已满足，退出重试循环。
            if "-4067" in message:  # 如果 Binance 仍提示存在未完成订单，就不要阻塞启动。
                print(f"[LIVE CONFIG] position_mode change deferred because open orders still exist symbol={SYMBOL}")  # 打印降级提示。
                break  # 保持当前账户状态继续启动，后续下单会按 positionSide 执行。
            raise  # 继续抛出异常，避免带着未知配置实盘。

    try:  # 尝试设置保证金模式。
        exchange.set_margin_mode(margin_mode, SYMBOL)  # 设置逐仓或全仓模式。
        print(f"[LIVE CONFIG] margin_mode={MARGIN_MODE} symbol={SYMBOL}")  # 打印保证金模式设置成功日志。
    except ccxt.AuthenticationError as exc:  # 如果只是认证失败，不阻塞启动。
        print(f"[LIVE CONFIG] skipped margin_mode setup due to auth error: {exc}")  # 打印认证问题提示。
    except ccxt.BaseError as exc:  # 捕获 ccxt 抛出的交易所异常。
        message = str(exc)  # 转成字符串用于判断是否只是“不需要修改”。
        if "No need to change margin type" in message or "not modified" in message.lower():  # Binance 已经是目标保证金模式时会报类似提示。
            print(f"[LIVE CONFIG] margin_mode already {MARGIN_MODE} symbol={SYMBOL}")  # 打印无需修改日志。
        elif "-4067" in message:  # 如果 Binance 仍提示存在未完成订单，就不要阻塞启动。
            print(f"[LIVE CONFIG] margin_mode change deferred because open orders still exist symbol={SYMBOL}")  # 打印降级提示。
        else:  # 如果不是已设置状态。
            raise  # 继续抛出异常，避免带着未知配置实盘。

    try:  # 尝试设置杠杆倍数。
        exchange.set_leverage(LEVERAGE, SYMBOL)  # 设置 Binance 合约杠杆倍数。
        print(f"[LIVE CONFIG] leverage={LEVERAGE}x symbol={SYMBOL}")  # 打印杠杆设置成功日志。
    except ccxt.AuthenticationError as exc:  # 如果只是认证失败，不阻塞启动。
        print(f"[LIVE CONFIG] skipped leverage setup due to auth error: {exc}")  # 打印认证问题提示。
