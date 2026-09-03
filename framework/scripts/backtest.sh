#!/usr/bin/env bash
# 遇到错误、未定义变量或管道失败时立即退出。
set -euo pipefail

# 切换到 framework 目录，保证相对路径稳定。
cd "$(dirname "$0")/.."

source ~/miniconda3/etc/profile.d/conda.sh
conda activate binance-bot

# 组装 RL 策略回测命令参数。
args=(
  backtesting
  --userdir
  user_data
  --config
  user_data/config_rl.json
  --strategy
  RlTradingStrategy
)

# 执行 Freqtrade 回测命令。
freqtrade "${args[@]}" "$@"
