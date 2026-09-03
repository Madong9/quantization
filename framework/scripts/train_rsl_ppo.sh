#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

source ~/miniconda3/etc/profile.d/conda.sh
conda activate binance-bot
export PYTHONPATH="$PWD/rsl_rl:${PYTHONPATH:-}"

python -m user_data.rl.train_rsl_ppo "$@"
