#!/usr/bin/env bash
# 运行 RL PPO 策略的 Freqtrade 交易。
#
# 默认仍是 dry-run 模拟盘：
#   bash scripts/dry_run_rl.sh
#
# Binance futures 测试网实测：
#   在 .env 或 .env.example 里设置 RL_TRADE_MODE=testnet 和测试网 key 后运行：
#   bash scripts/dry_run_rl.sh
set -euo pipefail

cd "$(dirname "$0")/.."

env_file=""
if [[ -f ".env" ]]; then
  env_file=".env"
elif [[ -f ".env.example" ]]; then
  env_file=".env.example"
fi

if [[ -n "$env_file" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    line="${line#export }"

    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -z "${!key+x}" ]] || continue

    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$env_file"
fi

source ~/miniconda3/etc/profile.d/conda.sh
conda activate binance-bot

mode="${RL_TRADE_MODE:-dry-run}"

args=(
  trade
  --userdir
  user_data
  --config
  user_data/config_rl.json
  --strategy
  RlTradingStrategy
)

if [[ "$mode" == "testnet" ]]; then
  BINANCE_TESTNET_KEY="${BINANCE_TESTNET_KEY:-${BINANCE_API_KEY:-}}"
  BINANCE_TESTNET_SECRET="${BINANCE_TESTNET_SECRET:-${BINANCE_API_SECRET:-}}"

  : "${BINANCE_TESTNET_KEY:?Set BINANCE_TESTNET_KEY before running testnet mode}"
  : "${BINANCE_TESTNET_SECRET:?Set BINANCE_TESTNET_SECRET before running testnet mode}"

  export FREQTRADE__DRY_RUN=false
  export FREQTRADE__DB_URL="${FREQTRADE__DB_URL:-sqlite:///user_data/tradesv3.testnet_rl.sqlite}"
  export FREQTRADE__EXCHANGE__KEY="$BINANCE_TESTNET_KEY"
  export FREQTRADE__EXCHANGE__SECRET="$BINANCE_TESTNET_SECRET"

  args+=(--config user_data/config_binance_testnet_rl.json)

  python - <<'PY'
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import ccxt


overlay = json.loads(Path("user_data/config_binance_testnet_rl.json").read_text())
exchange_cfg = copy.deepcopy(overlay["exchange"]["ccxt_config"])
exchange_cfg["apiKey"] = os.environ["FREQTRADE__EXCHANGE__KEY"]
exchange_cfg["secret"] = os.environ["FREQTRADE__EXCHANGE__SECRET"]

exchange = ccxt.binance(exchange_cfg)
mode_info = exchange.fetch_position_mode(params={"subType": "linear"})

if mode_info["hedged"]:
    raise SystemExit(
        "Binance USD-M futures account is still in Hedge Mode.\n"
        "Freqtrade only supports One-way Mode.\n"
        "Run: bash scripts/set_binance_testnet_one_way.sh\n"
        "If Binance refuses the change, close all testnet positions and cancel open orders first."
    )
PY

  echo "Starting RL strategy on Binance futures testnet."
  echo "Database: $FREQTRADE__DB_URL"
elif [[ "$mode" == "dry-run" ]]; then
  export FREQTRADE__DRY_RUN=true
  echo "Starting RL strategy in dry-run mode."
else
  echo "Unknown RL_TRADE_MODE: $mode" >&2
  echo "Use RL_TRADE_MODE=dry-run or RL_TRADE_MODE=testnet." >&2
  exit 1
fi

freqtrade "${args[@]}" "$@"
