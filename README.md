# Quantization Trading Projects

本仓库包含两套相互独立的交易策略工程：

- [`framework0`](framework0/)：普通规则策略。使用 `ccxt`、Binance USDT 合约行情和 EMA 交叉信号。
- [`framework`](framework/)：强化学习交易策略。基于 Freqtrade，并内置修改后的 `rsl_rl` PPO 训练与推理代码；同时保留 EMA 基线策略用于对照。

两个工程默认均以模拟交易/干跑模式运行。任何实盘使用都应先更换本地凭据、限制 API 权限并完成测试网验证。

## 凭据安全

真实密钥只应写入各工程本地的 `.env`，不得提交到 Git。仓库中的 `.env.example` 只包含空值或安全占位值：

```bash
cp framework/.env.example framework/.env
cp framework0/.env.example framework0/.env
```

训练数据、运行数据库、交易报告、训练 checkpoint 和发布归档均属于本地文件，已通过 `.gitignore` 排除。
