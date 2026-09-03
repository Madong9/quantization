# Freqtrade Binance Futures Project

这是一个独立的 Freqtrade 风格量化工程，默认连接 Binance USDT 合约市场，使用 `ETH/USDT:USDT`，策略为 `10 EMA / 30 EMA` 交叉。

默认是 `dry_run` 模拟盘，不会真实下单。

## 目录结构

```text
framework/
├── docker-compose.yml
├── requirements.txt
├── user_data/
│   ├── config.json
│   ├── data/
│   ├── logs/
│   └── strategies/
│       └── EmaCrossFuturesStrategy.py
└── scripts/
    ├── validate.sh
    ├── backtest.sh
  └── dry_run.sh
```

## 策略

- 交易所：Binance
- 市场：USDT 本位合约
- 交易对：`ETH/USDT:USDT`
- 保证金模式：`isolated`
- 周期：`1m`
- 做多：`10 EMA` 上穿 `30 EMA`
- 做空：`10 EMA` 下穿 `30 EMA`
- 杠杆：`5x`
- 模拟钱包：`1000 USDT`
- 仓位：`tradable_balance_ratio = 0.2`

Freqtrade futures 的 `minimal_roi` 和 `stoploss` 会按杠杆后的交易收益计算。当前策略里 `5x` 杠杆下：

- `minimal_roi = 0.05` 约等于价格朝盈利方向移动 `1%`
- `stoploss = -0.05` 约等于价格朝亏损方向移动 `1%`

## 强化学习

仓库内已经内置了 `rsl_rl`，所以可以直接用它的 PPO 和 OnPolicyRunner 来训练交易策略，而不再依赖外部强化学习库。

- 动作输出是 `0.0 - 1.0` 的连续值，`0.5` 是中立安全值
- `0.0 - 0.33` 映射为做空
- `0.33 - 0.67` 映射为中立/空仓
- `0.67 - 1.0` 映射为做多
- 观测包含最近 120 分钟的归一化市场特征窗口、前 120 次策略动作、配置向量和仓位状态
- 市场特征包括 returns、log_returns、volume_ratio、RSI、MACD、EMA ratio 和 volatility，不直接输入 raw close
- 奖励以权益 log return 为主并做单步裁剪，叠加手续费、回撤、空仓和盈利/亏损平仓的轻量惩罚/奖励
- TensorBoard 里会额外记录 actor/critic 的参数直方图和均值、标准差、范数等曲线

训练命令：

```bash
bash scripts/train_rsl_ppo.sh --iterations 200
```

默认数据源是 [user_data/data/binance/futures/ETH_USDT_USDT-1m-futures.feather](user_data/data/binance/futures/ETH_USDT_USDT-1m-futures.feather)，配置来源是 [user_data/config_rl.json](user_data/config_rl.json)。

## 使用 Docker 运行

```bash
cd framework
cp .env.example .env
docker compose run --rm freqtrade list-strategies --userdir /freqtrade/user_data
docker compose up
```

## 本地安装运行

```bash
cd framework
conda activate binance-bot
pip install -r requirements.txt
bash scripts/dry_run.sh
```

## 回测

先下载数据：

```bash
freqtrade download-data \
  --userdir user_data \
  --config user_data/config_rl.json \
  --exchange binance \
  --trading-mode futures \
  --timeframe 1m \
  --pairs ETH/USDT:USDT
```

再运行回测：

```bash
bash scripts/backtest.sh
```

## 重要说明

标准 Freqtrade 架构依赖交易所支持的 K 线周期，因此这个 Freqtrade 工程统一使用 `1m`。

实盘前请不要直接把 `dry_run` 改成 `false`。先完成测试网验证、最小下单量检查、API 权限隔离和风控审查。
