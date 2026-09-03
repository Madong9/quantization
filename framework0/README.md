# Binance 合约 EMA 交易脚本

这是一个使用 `ccxt` 编写的 Binance USDT 本位合约交易项目。默认运行“模拟交易模式”，只打印买卖信号、模拟开仓和平仓日志，不会提交真实订单。把配置和环境变量都显式打开后，可以发送真实 Binance 合约市价单。

## 策略说明

- 交易对：`ETH/USDT:USDT`
- 市场类型：Binance USDT 本位合约
- K 线周期：`1s`
- 买入信号：`10 EMA` 上穿 `30 EMA`
- 卖出信号：`10 EMA` 下穿 `30 EMA`
- 止损：`1%`
- 止盈：`1%`
- 仓位：每次使用可用 USDT 的 `1%` 作为保证金
- 杠杆：当前配置为 `3x`

## 项目结构

```text
.
├── binance_futures_ema_paper.py   # 程序入口
├── run.py                         # 主循环，负责调度行情、策略、风控和日志
├── config.py                      # 策略参数和运行配置
├── exchange/                      # 交易所访问相关代码
│   ├── create_exchange.py         # 创建 ccxt Binance 合约客户端
│   ├── fetch_closed_candles.py    # 获取已收盘 K 线
│   ├── get_available_usdt.py      # 获取可用 USDT，模拟模式失败时使用模拟余额
│   ├── live_guard.py              # 实盘启动前的安全检查
│   ├── open_live_position.py      # 实盘市价开仓
│   ├── close_live_position.py     # 实盘 reduceOnly 市价平仓
│   ├── set_leverage.py            # 设置实盘杠杆和保证金模式
│   └── websocket_one_second_candles.py # WebSocket 成交流聚合 1 秒 K线
├── strategy/                      # 策略计算相关代码
│   ├── ema.py                     # EMA 计算函数
│   └── detect_signal.py           # EMA 金叉 / 死叉信号检测
├── risk/                          # 持仓和风控相关代码
│   ├── position.py                # 持仓数据结构
│   ├── calculate_position.py      # 根据信号和余额计算模拟仓位
│   └── should_close_position.py   # 判断是否触发止盈止损
├── logging_utils/                 # 控制台日志输出
│   ├── print_position_open.py     # 打印开仓日志
│   └── print_position_close.py    # 打印平仓日志
└── utils/                         # 通用工具函数
    └── utc_now.py                 # 获取 UTC 当前时间
```

## 安装依赖

使用已有 conda 环境 `binance-bot`：

```bash
conda activate binance-bot
```

安装依赖：

```bash
cd framework0
pip install -r requirements.txt
```

## 运行

```bash
cd framework0
conda activate binance-bot
python3 binance_futures_ema_paper.py
```

程序会持续运行，每隔 `POLL_SECONDS` 秒检查一次行情。默认配置在 [config.py](config.py) 中：

```python
SYMBOL = "ETH/USDT:USDT"
TIMEFRAME = "1s"
FAST_EMA = 10
SLOW_EMA = 30
STOP_LOSS_PCT = 0.01
TAKE_PROFIT_PCT = 0.01
POSITION_FRACTION = 0.01
LEVERAGE = 3
POLL_SECONDS = 1
PAPER_TRADING = True
MARGIN_MODE = "ISOLATED"
MAX_LIVE_LEVERAGE = 20
FUTURES_WS_BASE_URL = "wss://fstream.binancefuture.com/ws"
FUTURES_TESTNET_WS_BASE_URL = "wss://stream.binancefuture.com/ws"
```

说明：Binance USDT 合约 REST K线接口不接受 `1s` interval。项目在 `TIMEFRAME = "1s"` 时不会请求交易所 1 秒 K线，而是订阅 Binance USD-M Futures WebSocket `@aggTrade` 成交流，用成交价和成交时间在本地聚合 1 秒 K线。默认 WebSocket 地址是 `wss://fstream.binancefuture.com/ws`；如果你的网络环境下 `wss://fstream.binance.com/ws` 能正常推送，也可以在 [config.py](config.py) 中切换。程序启动后需要先收集至少 `SLOW_EMA + 2` 根闭合秒线，期间会打印 `[WAIT] Collecting websocket 1s candles...`。

## 实时收益曲线

项目现在会把账户曲线实时写入 TensorBoard，而不是只在最后生成一张静态图。运行脚本时，每次处理一根 K 线都会写入：

- `equity/balance_usdt`：当前账户余额
- `equity/return_pct`：账户累计收益率，单位是 `%`
- `equity/realized_pnl_usdt`：累计已实现盈亏

TensorBoard 日志默认写到本次报告目录下的 `tensorboard` 子目录，例如：

```text
reports/run_20260505_062702_bj/tensorboard
```

启动交易脚本后，再开一个终端运行：

```bash
conda activate binance-bot
tensorboard --logdir reports
```

然后在浏览器里打开 TensorBoard 提示的地址，就能实时看到收益曲线。当前环境已经安装了 `tensorboard` 依赖。

如果你只是想看最后保存的静态图，脚本仍然会继续生成交易报告目录里的 PNG。

## 模拟余额

如果没有配置 Binance API，或者读取余额失败，程序会使用模拟余额。默认模拟余额是 `1000 USDT`。

注意：这个回退只用于 `PAPER_TRADING = True` 的模拟模式。实盘模式读取余额失败会直接停止，不会使用模拟余额继续下单。

可以通过环境变量修改：

```bash
conda activate binance-bot
PAPER_USDT_BALANCE=5000 python3 binance_futures_ema_paper.py
```

## Binance API 配置

模拟模式下，脚本可以读取 Binance 合约账户可用 USDT。需要配置：

```bash
export BINANCE_API_KEY="你的 API Key"
export BINANCE_API_SECRET="你的 API Secret"
```

然后运行：

```bash
conda activate binance-bot
python3 binance_futures_ema_paper.py
```

## 实盘运行

实盘会发送真实 Binance USDT 合约市价单：

- 开仓：`market` 市价单
- 平仓：`market` + `reduceOnly` 市价单
- 杠杆：启动时调用 `set_leverage`
- 保证金模式：启动时调用 `set_margin_mode`

当前版本的止盈止损由运行中的程序根据 1 秒聚合价格监控并平仓，不会自动在交易所挂原生保护单。因此实盘运行时不要关闭进程，也不要断网。

先在 [config.py](config.py) 里改成：

```python
PAPER_TRADING = False
```

建议实盘初期保持低杠杆和小仓位，例如：

```python
POSITION_FRACTION = 0.01
LEVERAGE = 3
```

使用 Binance Futures 测试网：

```bash
cd framework0
conda activate binance-bot

cp .env.example .env
# 然后编辑 .env，填入你的测试网 API Key / Secret

bash scripts/run_testnet.sh
```

设置 `BINANCE_TESTNET=true` 后，REST 交易接口和 1 秒 WebSocket 行情都会切到 Binance Futures 测试网。

也可以直接用脚本启动：

```bash
cd framework0
bash scripts/run_testnet.sh
```

使用 Binance 主网实盘：

```bash
cd framework0
conda activate binance-bot

cp .env.example .env
# 然后编辑 .env，填入你的主网 API Key / Secret，并移除 BINANCE_TESTNET=true

bash scripts/run_live.sh
```

也可以直接用脚本启动：

```bash
cd framework0
bash scripts/run_live.sh
```

如果 `LEVERAGE` 高于 `MAX_LIVE_LEVERAGE`，程序会拒绝启动。确实需要高杠杆时，要额外确认：

```bash
export ALLOW_HIGH_LEVERAGE=true
```

强烈建议先用测试网、极小仓位、低杠杆跑通完整开仓和平仓流程。

## 日志示例

没有信号时：

```text
[HEARTBEAT] price=65000.00 time=2026-05-04T15:00:00+08:00
```

出现金叉或死叉时：

```text
[SIGNAL] BUY price=65000.00 candle_close_bj=2026-05-04T15:00:00+08:00
[PAPER OPEN] LONG amount=0.003077 entry=65000.00 sl=64350.00 tp=66300.00 time=2026-05-04T15:00:02+08:00
```

触发止盈或止损时：

```text
[PAPER CLOSE] LONG reason=take_profit exit=66300.00 pnl=2.00% time=2026-05-04T15:30:00+08:00
```

实盘模式下，本地持仓日志前缀会显示为 `[LIVE OPEN]` 和 `[LIVE CLOSE]`。

## 风险提示

本项目仅用于学习和策略原型验证，不构成投资建议。合约交易风险很高，真实下单前需要充分测试，并确认 API 权限、仓位、杠杆和风控逻辑都符合你的预期。
