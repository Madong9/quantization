from __future__ import annotations  # 延迟解析类型注解，提升兼容性

import asyncio  # 用于运行 WebSocket 异步主循环
from datetime import datetime, timezone  # 处理 K 线时间戳转换
from zoneinfo import ZoneInfo
from typing import Optional  # 表示某些变量可以是指定类型，也可以是 None

import ccxt  # 使用 ccxt 的异常类型

from config import FAST_EMA, PAPER_TRADING, POLL_SECONDS, SLOW_EMA, STOP_LOSS_PCT, SYMBOL, TAKE_PROFIT_PCT, TIMEFRAME  # 导入运行配置
from exchange.create_exchange import create_exchange  # 导入交易所创建函数
from exchange.fetch_closed_candles import fetch_closed_candles  # 导入 K 线获取函数
from exchange.get_available_usdt import get_available_usdt  # 导入可用余额获取函数
from exchange.live_guard import ensure_live_trading_allowed  # 导入实盘启动安全检查函数
from exchange.open_live_position import open_live_position  # 导入实盘开仓函数
from exchange.set_leverage import configure_live_symbol  # 导入实盘交易对配置函数
from exchange.websocket_one_second_candles import iter_one_second_candles  # 导入 WebSocket 秒线异步生成器
from logging_utils.print_account_status import print_account_status  # 导入账户收益日志函数
from logging_utils.print_position_close import print_position_close  # 导入平仓日志函数
from logging_utils.print_position_open import print_position_open  # 导入开仓日志函数
from logging_utils.print_report_saved import print_report_saved  # 导入报告保存日志函数
from reporting.create_report_dir import create_report_dir  # 导入本次运行报告目录创建函数
from reporting.save_trade_report import save_trade_report  # 导入交易记录和曲线保存函数
from reporting.tensorboard_logger import TensorBoardLogger, create_tensorboard_logger  # 导入 TensorBoard 写入器
from risk.account import Account  # 导入账户收益数据结构
from risk.calculate_fees import estimate_futures_fee, get_futures_taker_fee_pct  # 导入手续费工具
from risk.calculate_position import calculate_position  # 导入仓位计算函数
from risk.calculate_pnl import calculate_pnl  # 导入盈亏计算函数
from risk.position import Position  # 导入持仓数据结构
from risk.should_close_position import should_close_position  # 导入止盈止损判断函数
from strategy.detect_signal import detect_signal  # 导入交易信号检测函数
from utils.utc_now import utc_now  # 导入 UTC 当前时间函数


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class TradingState:  # 定义类：保存主循环中的可变交易状态
    def __init__(self, account: Account, fee_pct: float) -> None:  # 初始化交易状态
        self.account = account  # 保存模拟账户
        self.fee_pct = fee_pct  # 保存从交易所读取或回退的合约 taker 手续费率
        self.available_balance = account.balance  # 保存可用于开仓的可用余额，和 wallet balance 分开
        self.position: Optional[Position] = None  # 初始化当前持仓为空
        self.live_positions: dict[str, Position] = {}  # 记录 live/testnet 下由交易所同步的持仓，按 long/short 分开
        self.last_signal_candle_ts: Optional[int] = None  # 记录上一次处理过的信号 K 线时间戳
        self.trade_id = 0  # 记录已经平仓的交易次数
        self.metric_step = 0  # TensorBoard 的递增步数


def _symbol_id() -> str:
    return SYMBOL.split(":")[0].replace("/", "")


def _build_position_from_exchange(raw_position: dict) -> Position:
    entry_price = float(raw_position.get("entryPrice", 0.0))
    amount = abs(float(raw_position.get("positionAmt", 0.0)))
    if entry_price <= 0 or amount <= 0:  # 过滤交易所返回的无效仓位，避免后续 PnL 计算崩溃
        raise ValueError("Invalid exchange position snapshot")  # 让上层跳过这个脏仓位

    leverage = int(float(raw_position.get("leverage", 0.0)) or 1)
    notional_usdt = abs(float(raw_position.get("notional", amount * entry_price)))
    margin_usdt = abs(float(raw_position.get("initialMargin", notional_usdt / leverage if leverage else 0.0)))
    side = "long" if raw_position.get("positionSide") == "LONG" else "short"

    stop_loss = entry_price * (1 - STOP_LOSS_PCT) if side == "long" else entry_price * (1 + STOP_LOSS_PCT)
    take_profit = entry_price * (1 + TAKE_PROFIT_PCT) if side == "long" else entry_price * (1 - TAKE_PROFIT_PCT)

    return Position(
        side=side,
        entry_price=entry_price,
        amount=amount,
        margin_usdt=margin_usdt,
        notional_usdt=notional_usdt,
        leverage=leverage,
        stop_loss=stop_loss,
        take_profit=take_profit,
        opened_at=utc_now(),
        entry_fee_usdt=0.0,
    )


def _infer_live_close_reason(position: Position, price: float) -> str:
    close_reason = should_close_position(position, price)
    return close_reason or "exchange_tp_sl"


def sync_live_state(exchange: ccxt.binance, state: TradingState, price: float, report_dir, tb_logger: TensorBoardLogger | None) -> bool:
    balance = exchange.fetch_balance({"type": "future"})
    info = balance.get("info", {})
    wallet_balance = float(info.get("totalWalletBalance", balance.get("free", state.account.balance)))
    available_balance = float(info.get("availableBalance", balance.get("free", wallet_balance)))
    state.account.balance = wallet_balance
    state.available_balance = available_balance
    state.account.realized_pnl = wallet_balance - state.account.initial_balance

    current_positions: dict[str, Position] = {}
    for raw_position in info.get("positions", []):
        if raw_position.get("symbol") != _symbol_id():
            continue
        if float(raw_position.get("positionAmt", 0.0)) == 0.0:
            continue

        try:  # 如果交易所返回了无效仓位快照就跳过
            position = _build_position_from_exchange(raw_position)
        except ValueError:
            continue
        current_positions[position.side] = position

    closed_any = False
    for side, previous_position in list(state.live_positions.items()):
        if side in current_positions:
            continue

        exit_fee_usdt = estimate_futures_fee(previous_position.amount * price, state.fee_pct)
        gross_pnl_usdt, pnl_pct = calculate_pnl(previous_position, price)
        realized_pnl_usdt = gross_pnl_usdt - previous_position.entry_fee_usdt - exit_fee_usdt
        balance_before = state.account.balance - realized_pnl_usdt
        state.account.fees_paid += exit_fee_usdt
        state.trade_id += 1
        csv_path, png_path = save_trade_report(state.trade_id, previous_position, price, _infer_live_close_reason(previous_position, price), balance_before, gross_pnl_usdt, exit_fee_usdt, state.account, report_dir)
        print_position_close(previous_position, price, "exchange_tp_sl", gross_pnl_usdt, exit_fee_usdt, realized_pnl_usdt, pnl_pct, state.account, "LIVE")
        print_report_saved(csv_path, png_path)
        closed_any = True

    state.live_positions = current_positions
    return closed_any


def log_account_metrics(logger: TensorBoardLogger | None, account: Account, positions: list[Position] | None, price: float, step: int) -> None:
    if logger is None:
        return

    unrealized_pnl = 0.0
    equity = account.balance
    if positions:
        for position in positions:
            position_unrealized_pnl, _ = calculate_pnl(position, price)
            unrealized_pnl += position_unrealized_pnl
        equity += unrealized_pnl

    logger.add_scalar("equity/balance_usdt", equity, step)
    logger.add_scalar("equity/wallet_balance_usdt", account.balance, step)
    logger.add_scalar("equity/unrealized_pnl_usdt", unrealized_pnl, step)
    logger.add_scalar("equity/return_pct", (equity - account.initial_balance) / account.initial_balance * 100 if account.initial_balance else 0.0, step)
    logger.add_scalar("equity/realized_pnl_usdt", account.realized_pnl, step)
    logger.add_scalar("equity/fees_paid_usdt", account.fees_paid, step)


def close_position(exchange: ccxt.binance, state: TradingState, price: float, reason: str, report_dir, tb_logger: TensorBoardLogger | None) -> None:  # 定义函数：根据当前模式平仓并记录结果
    if state.position is None:  # 如果当前没有持仓
        return  # 没有可平仓位时直接返回

    position = state.position  # 保存当前持仓，避免后续清空后无法记录
    if not PAPER_TRADING:  # 如果当前是实盘模式
        close_live_position(exchange, position, reason)  # 发送真实 reduceOnly 市价平仓单

    gross_pnl_usdt, pnl_pct = calculate_pnl(position, price)  # 计算本笔交易的 USDT 毛盈亏和收益率
    exit_fee_usdt = estimate_futures_fee(position.amount * price, state.fee_pct)  # 按实际费率估算本次平仓手续费
    realized_pnl_usdt = gross_pnl_usdt - position.entry_fee_usdt - exit_fee_usdt  # 成交后的已实现盈亏 = 毛盈亏 - 开平仓手续费
    balance_before = state.account.balance  # 记录平仓前账户余额
    state.account.apply_pnl(gross_pnl_usdt)  # 把毛盈亏计入本地账户曲线
    state.account.apply_fee(exit_fee_usdt)  # 把平仓手续费计入本地账户曲线
    state.trade_id += 1  # 平仓完成后交易编号加 1
    csv_path, png_path = save_trade_report(state.trade_id, position, price, reason, balance_before, gross_pnl_usdt, exit_fee_usdt, state.account, report_dir)  # 保存交易前后余额并更新曲线
    mode = "PAPER" if PAPER_TRADING else "LIVE"  # 根据当前开关生成日志模式名称
    print_position_close(position, price, reason, gross_pnl_usdt, exit_fee_usdt, realized_pnl_usdt, pnl_pct, state.account, mode)  # 打印平仓日志
    print_report_saved(csv_path, png_path)  # 打印报告文件保存位置
    state.position = None  # 清空当前持仓状态
    log_account_metrics(tb_logger, state.account, [], price, state.metric_step)  # 记录平仓后的账户曲线


def open_position(exchange: ccxt.binance, signal: str, price: float, state: TradingState) -> None:  # 定义函数：根据当前模式开仓
    trading_balance = state.available_balance if not PAPER_TRADING else state.account.balance  # live 模式用可用余额，paper 模式用脚本账户余额
    position = calculate_position(signal, price, trading_balance)  # 使用可用余额计算目标持仓
    position.entry_fee_usdt = estimate_futures_fee(position.notional_usdt, state.fee_pct)  # 按实际费率估算开仓手续费
    if not PAPER_TRADING:  # 如果当前是实盘模式
        if state.live_positions:  # 如果这个交易对已经有任何 live/testnet 仓位
            open_sides = ",".join(sorted(state.live_positions.keys()))  # 汇总当前持仓方向，方便日志查看
            print(f"[LIVE SIGNAL] skipped {position.side.upper()} because open position already exists: {open_sides}")  # 打印跳过信息
            return  # 不重复下单
        try:  # 尝试发送真实市价开仓单
            open_live_position(exchange, position)  # 发送真实市价开仓单
        except ccxt.InsufficientFunds as exc:  # 如果可用保证金不足
            print(f"[LIVE SIGNAL] skipped {position.side.upper()} due to insufficient funds: {exc}")  # 打印跳过信息
            return  # 不让程序崩溃
        state.account.fees_paid += position.entry_fee_usdt  # 将开仓手续费计入账户手续费统计
        state.live_positions[position.side] = position  # 记录 live/testnet 的持仓状态
        print("[LIVE WARNING] Stop-loss/take-profit are exchange-native orders; the script no longer closes positions manually.")  # 提醒当前版本依赖交易所保护单
        print_position_open(position, "LIVE")  # 打印 live 开仓日志
        return  # live 模式下直接结束

    state.account.apply_fee(position.entry_fee_usdt)  # 将开仓手续费计入账户
    state.position = position  # 真实下单成功或模拟模式下，记录本地持仓状态
    mode = "PAPER" if PAPER_TRADING else "LIVE"  # 根据当前开关生成日志模式名称
    print_position_open(state.position, mode)  # 打印开仓日志


def process_candles(exchange: ccxt.binance, candles: list[list[float]], state: TradingState, report_dir, tb_logger: TensorBoardLogger | None) -> None:  # 定义函数：处理一批闭合 K 线
    last_candle = candles[-1]  # 取最后一根已收盘 K 线
    last_candle_ts = int(last_candle[0])  # 取 K 线时间戳，ccxt OHLCV 的第 1 项是毫秒时间戳
    price = float(last_candle[4])  # 取最后一根已收盘 K 线的收盘价
    state.metric_step += 1  # 递增 TensorBoard 步数

    live_closed_this_candle = False  # 记录 live/testnet 模式下这根 K 线是否已有仓位被交易所平掉

    if not PAPER_TRADING:  # 如果当前是 live/testnet 模式
        live_closed_this_candle = sync_live_state(exchange, state, price, report_dir, tb_logger)  # 先同步交易所仓位和钱包余额
        current_positions = list(state.live_positions.values())  # 取当前 live/testnet 的所有持仓
    else:  # 如果当前是模拟模式
        current_positions = [state.position] if state.position else []  # 仅使用脚本维护的单一模拟持仓
        if state.position:  # 如果当前已经有模拟持仓
            close_reason = should_close_position(state.position, price)  # 检查是否触发止盈或止损
            if close_reason:  # 如果返回了平仓原因
                close_position(exchange, state, price, close_reason, report_dir, tb_logger)  # 根据当前模式执行平仓并记录报告
                live_closed_this_candle = True  # 模拟模式下同一根 K 线已发生平仓，避免立刻重开

    signal = detect_signal(candles)  # 检测当前是否出现 EMA 金叉或死叉信号
    if signal and state.last_signal_candle_ts != last_candle_ts:  # 如果有新信号，并且这根 K 线还没处理过
        candle_time = datetime.fromtimestamp(last_candle_ts / 1000, tz=timezone.utc).astimezone(BEIJING_TZ)  # 把毫秒时间戳转换为北京时间
        print(  # 开始打印信号日志
            f"[SIGNAL] {signal.upper()} price={price:.2f} "  # 打印信号方向和价格
            f"candle_close_bj={candle_time.isoformat()}"  # 打印信号对应的 K 线收盘时间
        )  # 信号日志打印结束
        state.last_signal_candle_ts = last_candle_ts  # 记录这根 K 线已经处理过，避免循环中重复触发

        if PAPER_TRADING:  # 模拟模式仍然使用单仓逻辑
            if state.position:  # 如果信号出现时已有持仓
                print(f"[SIGNAL] Ignored {signal.upper()} because paper position already exists: {state.position.side}")  # 打印忽略原因
            elif not live_closed_this_candle:  # 当前没有持仓且本根 K 线没有发生过平仓时，才允许按信号开仓
                open_position(exchange, signal, price, state)  # 根据当前模式打开新仓位
        else:  # live/testnet 模式只在没有同方向仓位时开仓，不再由脚本平仓
            if live_closed_this_candle:  # 如果这根 K 线里已经有仓位被交易所平掉
                print(f"[SIGNAL] Skipped {signal.upper()} because a TP/SL exit already happened this candle")  # 打印跳过信息
            elif state.live_positions:  # 如果当前这个交易对仍有任何 live/testnet 仓位
                open_sides = ",".join(sorted(state.live_positions.keys()))  # 汇总当前持仓方向，方便日志查看
                print(f"[SIGNAL] Skipped {signal.upper()} because live position already exists: {open_sides}")  # 打印跳过信息
            else:  # 没有同方向仓位才允许开仓
                try:  # 再加一层交易所错误保护，避免单笔下单失败导致主循环退出。
                    open_position(exchange, signal, price, state)  # 根据当前模式打开新仓位
                except ccxt.BaseError as exc:  # 捕获 Binance 返回的各类下单错误。
                    print(f"[LIVE SIGNAL] skipped {signal.upper()} due to exchange error: {exc}")  # 打印跳过信息。
    else:  # 如果没有新交易信号
        print(  # 开始打印心跳日志
            f"[HEARTBEAT] price={price:.8f} "  # 打印当前价格
            f"balance={state.account.balance:.2f} USDT "  # 打印当前账户余额
            f"account_return={state.account.return_pct * 100:.2f}% "  # 打印账户收益率
            f"time={utc_now().isoformat()}"  # 打印当前时间（北京时间）
        )  # 心跳日志打印结束

    if PAPER_TRADING:  # 模拟模式使用单一仓位计算权益
        metrics_positions = [state.position] if state.position else []  # 构造模拟模式持仓列表
    else:  # live/testnet 模式使用所有交易所同步的仓位计算权益
        metrics_positions = list(state.live_positions.values())  # 构造 live/testnet 持仓列表
    log_account_metrics(tb_logger, state.account, metrics_positions, price, state.metric_step)  # 每次处理后都写入最新账户状态


async def run_async() -> None:  # 定义异步主函数：运行交易循环
    ensure_live_trading_allowed()  # 实盘模式下先执行安全检查，模拟模式会直接返回
    exchange = create_exchange()  # 创建 Binance 合约交易所对象
    if not PAPER_TRADING:  # 如果当前是实盘模式
        configure_live_symbol(exchange)  # 设置实盘交易对的杠杆和保证金模式
    fee_pct = get_futures_taker_fee_pct(exchange, SYMBOL)  # 优先从交易所读取合约 taker 手续费率
    print(f"[FEES] taker_fee_pct={fee_pct:.6f} symbol={SYMBOL}")  # 打印实际费率，便于核对
    try:  # 尝试读取启动时可用 USDT。
        starting_balance = get_available_usdt(exchange)  # 获取启动时可用 USDT，作为模拟账户初始余额
    except RuntimeError as exc:  # 捕获余额读取失败。
        print(f"[ERROR] {exc}")  # 打印简洁错误，不展开 Python traceback。
        raise SystemExit(1) from exc  # 直接退出，让启动失败保持可读。
    state = TradingState(Account(initial_balance=starting_balance, balance=starting_balance), fee_pct=fee_pct)  # 创建模拟账户和交易状态
    report_dir = create_report_dir()  # 为本次运行创建独立的交易记录和曲线保存目录
    tb_logger = create_tensorboard_logger(report_dir / "tensorboard")  # 为本次运行创建 TensorBoard 日志目录

    mode = "PAPER" if PAPER_TRADING else "LIVE"  # 根据开关设置运行模式名称
    print(f"Starting {mode} trader: {SYMBOL}, {TIMEFRAME}, EMA {FAST_EMA}/{SLOW_EMA}")  # 打印启动信息
    print_account_status(state.account)  # 打印启动时的账户余额和收益状态
    print(f"[REPORT] current_run_dir={report_dir}")  # 打印本次运行的报告保存目录
    print(f"[TENSORBOARD] log_dir={report_dir / 'tensorboard'}")  # 打印 TensorBoard 日志目录
    log_account_metrics(tb_logger, state.account, [], starting_balance, state.metric_step)  # 写入初始账户状态

    try:
        if TIMEFRAME == "1s":  # 如果配置为 1 秒级策略
            async for candles in iter_one_second_candles(SYMBOL):  # 从 WebSocket 持续接收本地聚合秒线
                if len(candles) < SLOW_EMA + 2:  # 至少需要慢 EMA 周期加 2 根，才能判断前后两根交叉
                    print(f"[WAIT] Collecting websocket 1s candles: {len(candles)}/{SLOW_EMA + 2}")  # 打印收集进度
                    continue  # K 线不足时继续等待
                process_candles(exchange, candles, state, report_dir, tb_logger)  # K 线足够后执行策略处理
            return  # WebSocket 异步循环正常结束时返回

        while True:  # 非 1 秒周期时，继续使用 REST K 线循环
            try:  # 开始一次行情获取和策略判断
                candles = fetch_closed_candles(exchange)  # 获取已收盘 K 线
                process_candles(exchange, candles, state, report_dir, tb_logger)  # 执行策略处理
            except ccxt.NetworkError as exc:  # 捕获网络错误，例如连接超时或 DNS 问题
                print(f"[ERROR] Network issue: {exc}")  # 打印网络错误信息
            except ccxt.ExchangeError as exc:  # 捕获交易所返回的业务错误
                print(f"[ERROR] Exchange issue: {exc}")  # 打印交易所错误信息
            except RuntimeError as exc:  # 捕获运行时状态提示，例如 K 线正在收集
                print(f"[WAIT] {exc}")  # 打印等待信息，而不是当作严重错误
            except Exception as exc:  # 捕获其他未预料的异常，避免程序直接退出
                print(f"[ERROR] Unexpected issue: {exc}")  # 打印未知异常信息

            await asyncio.sleep(POLL_SECONDS)  # 等待指定秒数后进入下一轮检查
    finally:
        tb_logger.close()  # 确保 TensorBoard 写入器关闭并落盘


def run() -> None:  # 定义同步入口函数：启动异步主循环
    asyncio.run(run_async())  # 运行异步交易主循环
