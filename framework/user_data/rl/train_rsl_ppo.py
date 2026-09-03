from __future__ import annotations  # 启用未来注解语法，便于使用更现代的类型标注写法。

import argparse  # 提供命令行参数解析能力。
import os  # 提供操作系统相关工具，当前文件里主要用于路径与进程环境配合。
import sys  # 提供解释器运行时信息，这里用于把本地 rsl_rl 加入导入路径。
from pathlib import Path  # 提供跨平台路径对象，便于拼接项目内文件路径。

import torch  # type: ignore  # 用于检查 CUDA 是否可用，并规范设备名。


ROOT = Path(__file__).resolve().parents[2]  # 计算仓库根目录，后面所有默认路径都基于它。
RSL_RL_ROOT = ROOT / "rsl_rl"  # 指向仓库内 vendored 的 rsl_rl 目录。
if str(RSL_RL_ROOT) not in sys.path:  # 如果解释器还没看到这份本地框架，就手动加入。
    sys.path.insert(0, str(RSL_RL_ROOT))  # 优先使用仓库内的 rsl_rl，而不是环境里其他同名包。

from rsl_rl.runners import OnPolicyRunner  # type: ignore  # 导入 rsl_rl 的 on-policy 训练入口。

from .config import RslPpoTradingConfig  # 导入交易配置封装，负责读取 freqtrade config。
from .trading_env import RslTradingVecEnv, load_market_frame  # 导入交易环境和行情加载函数。


def normalize_device_name(device_name: str) -> str:  # 将命令行或脚本中的设备别名转换成 torch 能识别的名称。
    device_name = device_name.strip().lower()  # 统一去空格并转成小写。
    if device_name in {"gpu", "cuda"}:  # 把常见别名都映射到具体 CUDA 设备。
        return "cuda:0" if torch.cuda.is_available() else "cpu"  # 有 GPU 就用第一块卡，否则回退到 CPU。
    return device_name  # 其他设备名直接原样返回。


def build_train_cfg(num_steps_per_env: int) -> dict:  # 根据每个环境每轮采样步数，构造 rsl_rl 训练配置。
    return {  # 返回给 OnPolicyRunner 的完整配置字典。
        "num_steps_per_env": num_steps_per_env,  # 每次 rollout 每个环境采样多少步。
        "save_interval": 50,  # 每多少次迭代保存一次模型。
        "check_for_nan": True,  # 训练过程中检查 NaN，避免数值异常悄悄传播。
        "obs_groups": {"actor": ["policy"], "critic": ["policy"]},  # actor 和 critic 都读取 policy 观测组。
        "algorithm": {  # PPO 算法相关参数。
            "class_name": "PPO",  # 指定使用 rsl_rl 内置的 PPO 实现。
            "num_learning_epochs": 8,  # 每轮 rollout 后做多轮更新。
            "num_mini_batches": 4,  # 保持 batch 不过小，降低分钟行情噪声。
            "clip_param": 0.2,  # PPO ratio 裁剪范围。
            "gamma": 0.995,  # 分钟级交易不宜把未来折扣拉得过长。
            "lam": 0.95,  # GAE 的 lambda 参数。
            "value_loss_coef": 1.0,  # value loss 的权重。
            "entropy_coef": 0.02,  # 熵奖励的权重，用于鼓励探索。
            "learning_rate": 1e-4,  # 优化器初始学习率。
            "max_grad_norm": 1.0,  # 梯度裁剪阈值。
            "optimizer": "adam",  # 使用 Adam 优化器。
            "use_clipped_value_loss": True,  # 对 value loss 也做 PPO 式裁剪。
            "schedule": "adaptive",  # 按 KL 自适应调学习率。
            "desired_kl": 0.01,  # 目标 KL 值。
            "normalize_advantage_per_mini_batch": False,  # 不按每个 mini-batch 单独归一化优势。
            "share_cnn_encoders": False,  # 当前是纯 MLP，不共享 CNN 编码器。
            "rnd_cfg": None,  # 不启用随机网络蒸馏。
            "symmetry_cfg": None,  # 不启用对称增强。
        },
        "actor": {  # actor 网络结构配置。
            "class_name": "MLPModel",  # 使用 MLP 作为策略网络。
            "hidden_dims": [512, 256, 128],  # 分钟行情样本有限，网络太大容易把噪声学满。
            "activation": "elu",  # 激活函数使用 ELU。
            "obs_normalization": True,  # 对输入观测做在线归一化。
            "distribution_cfg": {  # 动作分布配置。
                "class_name": "BetaDistribution",  # 用 Beta 分布把动作限制在 [0,1]。
                "action_range": [0.0, 1.0],  # Beta 输出再映射到 0 到 1 的动作区间。
            },
        },
        "critic": {  # critic 网络结构配置。
            "class_name": "MLPModel",  # 使用 MLP 作为价值网络。
            "hidden_dims": [512, 256, 128],  # 与 actor 保持一致。
            "activation": "elu",  # 激活函数使用 ELU。
            "obs_normalization": True,  # 对输入观测做在线归一化。
        },
    }  # 结束训练配置字典。


def main() -> None:  # 程序入口，负责解析参数、构造环境并启动训练。
    parser = argparse.ArgumentParser(description="Train a PPO policy with the vendored rsl_rl framework.")  # 创建命令行解析器。
    parser.add_argument(  # 定义行情数据路径参数。
        "--data-path",  # 参数名。
        type=Path,  # 以 Path 对象读取，方便后续路径处理。
        default=ROOT / "user_data/data/binance/futures/ETH_USDT_USDT-1m-futures.feather",  # 默认读取 1 分钟合约数据。
    )  # 结束数据路径参数定义。
    parser.add_argument("--config-path", type=Path, default=ROOT / "user_data/config_rl.json")  # 定义 freqtrade 配置文件路径。
    parser.add_argument("--log-dir", type=Path, default=ROOT / "user_data/rl/logs")  # 定义 TensorBoard/日志输出目录。
    parser.add_argument("--export-dir", type=Path, default=ROOT / "user_data/rl/models")  # 定义模型导出目录。
    parser.add_argument("--num-envs", type=int, default=8)  # 定义并行环境数量。
    parser.add_argument("--num-steps-per-env", type=int, default=512)  # 定义每轮 rollout 的步数。
    parser.add_argument("--iterations", type=int, default=200)  # 定义训练迭代轮数。
    parser.add_argument("--episode-length", type=int, default=72000)  # 定义单个 episode 的最大长度。
    parser.add_argument("--window-size", type=int, default=1200)  # 定义观测价格窗口长度。
    parser.add_argument("--action-history-size", type=int, default=1200)  # 定义观测动作历史长度。
    parser.add_argument("--fee-rate", type=float, default=0.0005)  # 定义交易手续费率。
    parser.add_argument("--leverage", type=float, default=50.0)  # 定义策略使用的杠杆倍数。
    parser.add_argument("--device", type=str, default="cpu")  # 定义训练设备，默认使用 CPU。
    args = parser.parse_args()  # 解析命令行参数。

    device_name = normalize_device_name(args.device)  # 先把设备别名规范化，避免 torch.device 解析失败。

    cfg = RslPpoTradingConfig.from_freqtrade_config(  # 从 freqtrade 配置构造 RL 专用配置。
        args.config_path,  # 读取配置文件路径。
        fee_rate=args.fee_rate,  # 使用命令行指定的手续费率。
        leverage=args.leverage,  # 使用命令行指定的杠杆倍数。
        window_size=args.window_size,  # 使用命令行指定的窗口长度。
        action_history_size=args.action_history_size,  # 使用命令行指定的动作历史长度。
        episode_length=args.episode_length,  # 使用命令行指定的 episode 长度。
    )  # 结束 RL 配置构造。

    market_frame = load_market_frame(args.data_path)  # 读取并整理行情数据。
    env = RslTradingVecEnv(market_frame=market_frame, cfg=cfg, num_envs=args.num_envs, device=device_name)  # 构造并行交易环境。

    train_cfg = build_train_cfg(args.num_steps_per_env)  # 根据 rollout 长度生成训练配置。
    runner = OnPolicyRunner(env, train_cfg, log_dir=str(args.log_dir), device=device_name)  # 用 rsl_rl Runner 组装 PPO 训练器。
    runner.learn(num_learning_iterations=args.iterations, init_at_random_ep_len=False)  # 开始训练，不随机打乱初始 episode 位置。

    args.export_dir.mkdir(parents=True, exist_ok=True)  # 确保导出目录存在。
    runner.save(str(args.export_dir / "checkpoint.pt"))  # 保存完整训练 checkpoint。
    runner.export_policy_to_jit(str(args.export_dir), filename="policy.pt")  # 导出可推理的 TorchScript policy。
    print(f"saved PPO checkpoint to {args.export_dir / 'checkpoint.pt'}")  # 打印 checkpoint 保存结果。
    print(f"exported policy to {args.export_dir / 'policy.pt'}")  # 打印 policy 导出结果。


if __name__ == "__main__":  # 仅当文件被直接执行时运行入口函数。
    main()  # 启动训练流程。
