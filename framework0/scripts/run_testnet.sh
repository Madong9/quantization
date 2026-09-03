#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
	set -a
	# shellcheck disable=SC1091
	. ./.env
	set +a
fi

export BINANCE_TESTNET=true
export BINANCE_API_KEY="${BINANCE_API_KEY:?Set BINANCE_API_KEY in .env or your shell}"
export BINANCE_API_SECRET="${BINANCE_API_SECRET:?Set BINANCE_API_SECRET in .env or your shell}"
export ENABLE_BINANCE_LIVE_TRADING="${ENABLE_BINANCE_LIVE_TRADING:-I_UNDERSTAND_THIS_IS_REAL_MONEY}"

python3 binance_futures_ema_paper.py