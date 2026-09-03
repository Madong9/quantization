#!/usr/bin/env bash
# Switch the Binance USD-M futures testnet/demo account to One-way Mode.
# Freqtrade does not support Hedge Mode.
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

python - <<'PY'
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import ccxt


key = os.environ.get("BINANCE_TESTNET_KEY") or os.environ.get("BINANCE_API_KEY")
secret = os.environ.get("BINANCE_TESTNET_SECRET") or os.environ.get("BINANCE_API_SECRET")
if not key or not secret:
    raise SystemExit("Set BINANCE_TESTNET_KEY/BINANCE_TESTNET_SECRET or BINANCE_API_KEY/BINANCE_API_SECRET in .env first.")

overlay = json.loads(Path("user_data/config_binance_testnet_rl.json").read_text())
exchange_cfg = copy.deepcopy(overlay["exchange"]["ccxt_config"])
exchange_cfg["apiKey"] = key
exchange_cfg["secret"] = secret

exchange = ccxt.binance(exchange_cfg)
before = exchange.fetch_position_mode(params={"subType": "linear"})
print(f"Current USD-M futures position mode: {'Hedge' if before['hedged'] else 'One-way'}")
if before["hedged"]:
    print("Switching USD-M futures position mode to One-way...")
    try:
        response = exchange.set_position_mode(False, params={"subType": "linear"})
    except ccxt.BaseError as exc:
        raise SystemExit(
            f"Could not switch to One-way Mode: {exc}\n"
            "Close all testnet futures positions and cancel open orders, then run this script again."
        ) from exc
    print(f"Change response: {response}")
    after = exchange.fetch_position_mode(params={"subType": "linear"})
    print(f"New USD-M futures position mode: {'Hedge' if after['hedged'] else 'One-way'}")
else:
    print("No change needed.")
PY
