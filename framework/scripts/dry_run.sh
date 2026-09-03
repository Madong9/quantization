#!/usr/bin/env bash
# 遇到错误、未定义变量或管道失败时立即退出。
set -euo pipefail

# 切换到 framework 目录，保证相对路径稳定。
cd "$(dirname "$0")/.."

# 组装 Freqtrade 模拟交易命令参数。
args=( # 使用数组保存参数，避免续行注释影响 shell 解析。
  trade # 运行 Freqtrade 交易子命令，当前配置为 dry_run 模拟盘。
  --userdir # 声明下一项是用户数据目录。
  user_data # 指定 Freqtrade 用户数据目录。
  --config # 声明下一项是配置文件路径。
  user_data/config.json # 指定默认配置文件。
  --strategy # 声明下一项是策略类名。
  EmaCrossFuturesStrategy # 指定要运行的策略类。
) # 结束模拟交易命令参数数组。

# 执行 Freqtrade 模拟交易命令。
freqtrade "${args[@]}"
