#!/usr/bin/env bash
# 遇到错误、未定义变量或管道失败时立即退出。
set -euo pipefail

# 切换到 framework 目录，保证相对路径稳定。
cd "$(dirname "$0")/.."

# 组装策略列表校验命令参数。
list_strategy_args=( # 使用数组保存 list-strategies 参数。
  list-strategies # 运行 Freqtrade 策略列表子命令。
  --userdir # 声明下一项是用户数据目录。
  user_data # 指定 Freqtrade 用户数据目录。
) # 结束策略列表校验命令参数数组。

# 执行策略列表校验命令。
freqtrade "${list_strategy_args[@]}"

# 组装交易对列表校验命令参数。
test_pairlist_args=( # 使用数组保存 test-pairlist 参数。
  test-pairlist # 运行 Freqtrade 交易对列表校验子命令。
  --config # 声明下一项是配置文件路径。
  user_data/config.json # 指定默认配置文件。
) # 结束交易对列表校验命令参数数组。

# 执行交易对列表校验命令。
freqtrade "${test_pairlist_args[@]}"
