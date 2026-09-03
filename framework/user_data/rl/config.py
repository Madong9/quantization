from __future__ import annotations  # 启用未来注解语法，方便使用更现代的类型标注。

import json  # 读取和解析 JSON 配置文件。
import re  # 用正则表达式解析时间周期字符串。
from dataclasses import asdict, dataclass  # 提供 dataclass 装饰器和对象转字典工具。
from pathlib import Path  # 提供跨平台路径处理能力。


def _coerce_float(value: object, default: float) -> float:  # 尝试把输入值安全地转成浮点数。
    try:  # 进入数值转换尝试分支。
        return float(value)  # 如果成功，直接返回浮点数。
    except (TypeError, ValueError):  # 如果类型不对或内容无法转换，就走兜底分支。
        return default  # 返回默认值，避免配置读取中断。


def _parse_timeframe_minutes(value: object, default: int = 1) -> int:  # 把 freqtrade 的周期字符串转成分钟数。
    if isinstance(value, int):  # 如果已经是整数，直接当成分钟数处理。
        return max(1, value)  # 最少返回 1 分钟，避免非法 0 值。
    if not isinstance(value, str):  # 如果既不是整数也不是字符串，就返回默认值。
        return default  # 使用默认分钟数。

    match = re.fullmatch(r"(\d+)([mhd])", value.strip().lower())  # 匹配如 1m、4h、1d 这样的格式。
    if not match:  # 如果格式不符合预期，就直接回退默认值。
        return default  # 返回默认分钟数。

    amount = int(match.group(1))  # 取出数值部分，比如 1h 里的 1。
    unit = match.group(2)  # 取出单位部分，比如 m、h 或 d。
    if unit == "m":  # 如果单位是分钟。
        return max(1, amount)  # 直接返回分钟数。
    if unit == "h":  # 如果单位是小时。
        return max(1, amount * 60)  # 转成分钟数返回。
    if unit == "d":  # 如果单位是天。
        return max(1, amount * 60 * 24)  # 转成分钟数返回。
    return default  # 兜底返回默认值。


@dataclass(frozen=True)  # 把交易所需参数定义成不可变数据类。
class RslPpoTradingConfig:  # PPO 交易环境使用的配置集合。
    window_size: int = 1200  # 观测里回看多少根 1 分钟 K 线中值。
    action_history_size: int = 1200  # 观测里回看多少次历史动作。
    episode_length: int = 72000  # 一个 episode 最多走多少步。
    timeframe_minutes: int = 1  # 当前训练使用的周期长度，单位分钟。
    fee_rate: float = 0.0005  # 单边手续费率。
    leverage: float = 10.0  # 使用的杠杆倍数。
    stake_amount: float = 1000.0  # 模拟起始资金。
    tradable_balance_ratio: float = 0.2  # 每次允许投入的资金比例。
    minimal_roi: float = 0.20  # 达到的止盈阈值。
    stoploss: float = -0.20  # 触发的止损阈值。
    max_open_trades: int = 1  # 同时允许的最大持仓数量。
    process_throttle_secs: int = 5  # 配置里的内部节流秒数。
    short_action_threshold: float = 1.0 / 3.0  # 动作小于该值时开空。
    long_action_threshold: float = 2.0 / 3.0  # 动作大于该值时开多，中间区间保持观望。
    min_equity_ratio: float = 0.05  # 权益低于初始资金这个比例时提前结束 episode。
    reward_equity_scale: float = 200.0  # 权益变化奖励缩放，避免分钟级收益信号太弱。
    reward_fee_weight: float = 2.0  # 手续费惩罚的权重。
    reward_flat_penalty: float = 0.00005  # 空仓且继续观望时的极小惩罚，降低永远不交易的吸引力。
    reward_closed_trade_bonus: float = 0.02  # 盈利/亏损平仓的轻量额外奖励或惩罚。
    reward_drawdown_weight: float = 0.05  # 回撤惩罚的权重。
    reward_clip: float = 5.0  # 单步奖励裁剪范围，避免破产步产生极端优势值。

    @classmethod  # 声明这是一个类方法，用来从 freqtrade 配置生成 RL 配置。
    def from_freqtrade_config(  # 从 freqtrade 的 config.json 读取并映射到本配置结构。
        cls,  # 类本身。
        config_path: str | Path,  # freqtrade 配置文件路径。
        *,  # 后面的参数必须显式命名传入。
        fee_rate: float = 0.0005,  # 允许外部覆盖手续费率。
        leverage: float = 10.0,  # 允许外部覆盖杠杆倍数。
        window_size: int = 1200,  # 允许外部覆盖观测窗口长度。
        action_history_size: int = 1200,  # 允许外部覆盖动作历史长度。
        episode_length: int = 72000,  # 允许外部覆盖 episode 长度。
    ) -> "RslPpoTradingConfig":  # 返回一个新的 RL 配置对象。
        raw = json.loads(Path(config_path).read_text())  # 读取并解析 JSON 配置文件。
        return cls(  # 根据 freqtrade 配置和命令行参数构造新的配置对象。
            window_size=window_size,  # 设置观测窗口长度。
            action_history_size=action_history_size,  # 设置历史动作窗口长度。
            episode_length=episode_length,  # 设置 episode 长度。
            timeframe_minutes=_parse_timeframe_minutes(raw.get("timeframe"), 1),  # 从配置中解析周期分钟数。
            fee_rate=fee_rate,  # 使用传入的手续费率。
            leverage=leverage,  # 使用传入的杠杆倍数。
            stake_amount=_coerce_float(raw.get("dry_run_wallet", 1000.0), 1000.0),  # 读取模拟钱包金额。
            tradable_balance_ratio=_coerce_float(raw.get("tradable_balance_ratio", 0.2), 0.2),  # 读取可交易资金比例。
            minimal_roi=0.20,  # 这里固定使用与原策略一致的止盈阈值。
            stoploss=-0.20,  # 这里固定使用与原策略一致的止损阈值。
            max_open_trades=int(raw.get("max_open_trades", 1)),  # 读取最大持仓数。
            process_throttle_secs=int(raw.get("internals", {}).get("process_throttle_secs", 5)),  # 读取内部节流设置。
        )  # 返回构造完成的配置对象。

    def to_vector(self) -> list[float]:  # 把配置压成数值向量，供策略作为观测输入。
        return [  # 返回一个标准化后的配置向量。
            float(self.window_size) / 1200.0,  # 观测窗口归一化。
            float(self.action_history_size) / 1200.0,  # 动作历史长度归一化。
            float(self.episode_length) / 72000.0,  # episode 长度归一化。
            float(self.timeframe_minutes) / 1.0,  # 周期分钟数归一化。
            float(self.fee_rate) * 10_000.0,  # 手续费率放大到更容易学习的尺度。
            float(self.leverage) / 10.0,  # 杠杆倍数归一化。
            float(self.stake_amount) / 1000.0,  # 资金规模归一化。
            float(self.tradable_balance_ratio),  # 资金使用比例直接输入。
            float(self.minimal_roi),  # 止盈阈值直接输入。
            abs(float(self.stoploss)),  # 止损阈值取绝对值后输入。
            float(self.max_open_trades),  # 最大持仓数直接输入。
            float(self.process_throttle_secs) / 5.0,  # 节流秒数归一化。
        ]  # 结束配置向量列表。

    def to_dict(self) -> dict:  # 把数据类转成字典，便于环境里直接挂到 cfg 上。
        data = asdict(self)  # 先将 dataclass 展开成普通字典。
        data["config_vector"] = self.to_vector()  # 再补充一个已归一化的配置向量。
        return data  # 返回完整字典。
