"""
Freqtrade strategy using a TorchScript PPO policy trained in user_data.rl.

The policy outputs one continuous action in [0, 1]:
    0.00 - 0.33 -> short
    0.33 - 0.67 -> neutral / no-trade
    0.67 - 1.00 -> long

The action only chooses the entry direction. Exits are controlled by the net
take-profit and stoploss rules.
"""

from __future__ import annotations

import os
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from pandas import DataFrame, Timestamp

from freqtrade.exchange import timeframe_to_next_date, timeframe_to_prev_date
from freqtrade.strategy import IStrategy
from user_data.rl.features import MARKET_FEATURE_COLUMNS, add_market_features


# Freqtrade 策略在某些测试/直接实例化场景下不一定挂 self.logger，
# 所以这里使用模块级 logger，避免策略加载时因为日志对象缺失而报错。
logger = logging.getLogger(__name__)


class RlTradingStrategy(IStrategy):
    """Run a pre-trained RSL-RL PPO policy inside Freqtrade."""

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1m"
    process_only_new_candles = True

    window_size: int = 1200
    action_history_size: int = 1200
    startup_candle_count = window_size + action_history_size

    minimal_roi = {"0": 0.01}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    max_open_trades = 1

    policy_path: str = str(Path(__file__).resolve().parents[2] / "user_data/rl/models/policy.pt")

    episode_length: int = 72000
    fee_rate: float = 0.0005
    leverage_value: float = 50.0
    # Freqtrade 会把 stake_amount 覆盖为配置里的 "unlimited"。
    # RL 观测需要数值资金规模，所以单独使用 rl_stake_amount。
    rl_stake_amount: float = 1000.0
    tradable_balance_ratio: float = 0.2
    minimal_roi_rl: float = 0.01
    stoploss_rl: float = -0.10
    process_throttle_secs: int = 5

    neutral_action_value: float = 0.50
    short_action_threshold: float = 1.0 / 3.0
    long_action_threshold: float = 2.0 / 3.0

    # TorchScript policy 和运行设备在 __init__ 中加载；放在类属性上便于类型提示。
    _policy: torch.jit.ScriptModule | None = None
    _device: torch.device | None = None
    _warned_policy_shape_mismatch: bool = False
    _last_entry_candle_by_pair: dict[tuple[str, str], datetime]
    _last_exit_check_candle_by_trade: dict[int | str, datetime]

    def __init__(self, config: dict) -> None:
        """加载配置和 TorchScript policy。

        这些参数必须和训练时的 RslPpoTradingConfig 保持一致，否则模型看到的
        配置向量会偏移，推理输出就没有训练语义。
        """
        super().__init__(config)

        # 从 Freqtrade 配置同步资金/仓位参数，避免策略文件里的默认值和 config_rl.json 脱节。
        self.rl_stake_amount = float(config.get("dry_run_wallet", self.rl_stake_amount))
        self.tradable_balance_ratio = float(config.get("tradable_balance_ratio", self.tradable_balance_ratio))
        self.max_open_trades = int(config.get("max_open_trades", self.max_open_trades))
        self.process_throttle_secs = int(
            config.get("internals", {}).get("process_throttle_secs", self.process_throttle_secs)
        )
        self.short_action_threshold = float(config.get("rl_short_action_threshold", self.short_action_threshold))
        self.long_action_threshold = float(config.get("rl_long_action_threshold", self.long_action_threshold))
        if not 0.0 <= self.short_action_threshold < self.long_action_threshold <= 1.0:
            raise ValueError("rl_short_action_threshold must be < rl_long_action_threshold and both must be within [0, 1]")
        self._last_entry_candle_by_pair = {}
        self._last_exit_check_candle_by_trade = {}

        self._device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        policy_file = config.get("rl_policy_path", self.policy_path)
        if not os.path.isfile(policy_file):
            raise FileNotFoundError(f"RL policy file not found: {policy_file}")

        # policy.pt 是 train_rsl_ppo.py 导出的 TorchScript，只需要 eval 推理，不参与训练。
        self._policy = torch.jit.load(policy_file, map_location=self._device)
        self._policy.eval()
        logger.info(f"Loaded RL policy from {policy_file} on {self._device}")

    def _timeframe_minutes(self) -> int:
        """把 Freqtrade 的周期字符串转换成分钟数，用于配置向量和持仓年龄归一化。"""
        value = self.timeframe.strip().lower()
        if value.endswith("m"):
            return max(1, int(value[:-1]))
        if value.endswith("h"):
            return max(1, int(value[:-1]) * 60)
        if value.endswith("d"):
            return max(1, int(value[:-1]) * 1440)
        return 1

    def _dataframe_until(self, dataframe: DataFrame | None, current_time) -> DataFrame | None:
        """截取到 current_time 为止的数据，避免回测回调读取未来 K 线。

        Freqtrade 在回测中传给回调的 analyzed dataframe 有时包含完整区间数据；
        如果直接用 dataframe.iloc[-1]，可能拿到未来蜡烛，导致严重的前视偏差。
        """
        if dataframe is None or current_time is None or "date" not in dataframe.columns:
            return dataframe

        compare_time = Timestamp(current_time)
        date_series = dataframe["date"]
        try:
            mask = date_series <= compare_time
        except TypeError:
            # pandas 对 tz-aware / tz-naive 时间比较很严格，这里按行情列的时区做一次对齐。
            date_tz = getattr(date_series.dt, "tz", None)
            if date_tz is not None and compare_time.tzinfo is None:
                compare_time = compare_time.tz_localize(date_tz)
            elif date_tz is None and compare_time.tzinfo is not None:
                compare_time = compare_time.tz_localize(None)
            mask = date_series <= compare_time

        return dataframe.loc[mask]

    def _current_candle_date(self, current_time) -> datetime | None:
        """Return the open time of the candle currently being processed."""
        if current_time is None:
            return None
        return timeframe_to_prev_date(self.timeframe, current_time)

    def _next_candle_date(self, current_time) -> datetime | None:
        """Return the next candle open time, used for same-candle entry locks."""
        if current_time is None:
            return None
        return timeframe_to_next_date(self.timeframe, current_time)

    def _action_to_signal(self, action_value: float) -> str:
        """把连续动作映射成交易方向。

        action 只决定空仓时是否开多/开空；中间区间保持观望，不负责平仓。
        """
        if action_value < self.short_action_threshold:
            return "short"
        if action_value > self.long_action_threshold:
            return "long"
        return "neutral"

    def _config_vector(self) -> torch.Tensor:
        """构造与训练环境 RslPpoTradingConfig.to_vector() 对齐的配置向量。"""
        return torch.tensor(
            [
                float(self.window_size) / 1200.0,
                float(self.action_history_size) / 1200.0,
                float(self.episode_length) / 72000.0,
                float(self._timeframe_minutes()) / 1.0,
                float(self.fee_rate) * 10_000.0,
                float(self.leverage_value) / 10.0,
                float(self.rl_stake_amount) / 1000.0,
                float(self.tradable_balance_ratio),
                float(self.minimal_roi_rl),
                abs(float(self.stoploss_rl)),
                float(self.max_open_trades),
                float(self.process_throttle_secs) / 5.0,
            ],
            dtype=torch.float32,
        )

    def _normalized_action_history(self, values: Iterable[float] | None) -> torch.Tensor:
        """整理动作历史，长度不足时用中立动作补齐。

        训练环境里 observation 包含最近 action_history_size 个动作；实盘刚启动时没有
        足够历史动作，用 0.5 补齐可以保持“安全中立”的语义。
        """
        if values is None:
            items: list[float] = []
        else:
            items = [float(np.clip(value, 0.0, 1.0)) for value in values]
        if len(items) < self.action_history_size:
            items = [self.neutral_action_value] * (self.action_history_size - len(items)) + items
        return torch.tensor(items[-self.action_history_size :], dtype=torch.float32)

    def _action_history_from_frame(self, dataframe: DataFrame) -> list[float]:
        """从已分析 dataframe 中取最近 RL 动作，供退出推理复用。"""
        if "rl_action" not in dataframe.columns:
            return [self.neutral_action_value] * self.action_history_size

        values = dataframe["rl_action"].dropna().tail(self.action_history_size).to_list()
        values = [float(np.clip(value, 0.0, 1.0)) for value in values]
        if len(values) < self.action_history_size:
            values = [self.neutral_action_value] * (self.action_history_size - len(values)) + values
        return values

    def _trade_position_age(self, trade, current_time: datetime | None) -> int:
        """计算当前持仓已经经过多少根策略周期。"""
        if trade is None or current_time is None:
            return 0

        open_time = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if open_time is None:
            return 0

        if open_time.tzinfo is None and current_time.tzinfo is not None:
            open_time = open_time.replace(tzinfo=current_time.tzinfo)
        if current_time.tzinfo is None and open_time.tzinfo is not None:
            current_time = current_time.replace(tzinfo=open_time.tzinfo)

        elapsed = max(0.0, (current_time - open_time).total_seconds())
        return int(elapsed // (self._timeframe_minutes() * 60))

    def _trade_state(
        self,
        trade,
        *,
        current_time: datetime | None,
        current_rate: float | None,
        reference_price: float,
    ) -> tuple[int, float, float, float, float, int]:
        """把 Freqtrade Trade 对象转换成训练环境中的持仓状态特征。

        训练环境需要方向、入场价、现金/权益、持仓规模、未实现盈亏、杠杆收益和持仓年龄；
        这里不用 Freqtrade 的内部利润 API，避免不同版本 API 名称差异。
        """
        if trade is None:
            return 0, 0.0, self.rl_stake_amount, self.rl_stake_amount, 0.0, 0.0, 0

        position_side = -1 if trade.is_short else 1
        entry_price = float(trade.open_rate)
        position_quantity = float(trade.amount)
        price = float(current_rate) if current_rate and current_rate > 0 else reference_price

        open_notional = abs(position_quantity * entry_price)
        open_fee = open_notional * self.fee_rate
        unrealized = position_side * position_quantity * (price - entry_price)
        cash_balance = self.rl_stake_amount - open_fee
        equity = cash_balance + unrealized
        position_age = self._trade_position_age(trade, current_time)

        return position_side, entry_price, cash_balance, equity, position_quantity, open_notional, position_age

    def _build_observation(
        self,
        dataframe: DataFrame,
        current_index: int,
        *,
        trade=None,
        current_time: datetime | None = None,
        current_rate: float | None = None,
        action_history: Iterable[float] | None = None,
        closed_trades: int = 0,
    ) -> torch.Tensor:
        """构造 PPO policy 的观测向量。

        观测顺序必须与 user_data.rl.trading_env.RslTradingVecEnv._build_observation 一致：
        市场特征窗口、动作历史、配置向量、持仓状态特征。
        """
        start = current_index - self.window_size + 1
        reference_price = max(float(dataframe["mid"].iloc[current_index]), 1e-8)
        # 不直接喂 raw close/mid；每根 K 线输入 return、ratio、RSI、MACD、波动率等稳定特征。
        feature_window = dataframe.loc[start:current_index, MARKET_FEATURE_COLUMNS].to_numpy(dtype=np.float32).reshape(-1)

        position_side, entry_price, cash_balance, equity, position_quantity, position_notional, position_age = self._trade_state(
            trade,
            current_time=current_time,
            current_rate=current_rate,
            reference_price=reference_price,
        )

        episode_step = min(max(current_index - self.window_size + 1, 1), self.episode_length)
        entry_offset = (entry_price / reference_price - 1.0) if position_side != 0 else 0.0
        unrealized_pnl = equity - cash_balance if position_side != 0 else 0.0
        leveraged_return = (unrealized_pnl / max(position_notional, 1e-8)) * self.leverage_value if position_side != 0 else 0.0
        # 状态特征的尺度要和训练环境一致，否则 policy 的归一化统计会失效。
        state_features = torch.tensor(
            [
                float(position_side),
                float(entry_offset),
                cash_balance / max(self.rl_stake_amount, 1e-8),
                equity / max(self.rl_stake_amount, 1e-8),
                float(position_quantity),
                position_notional / max(self.rl_stake_amount, 1e-8),
                unrealized_pnl / max(self.rl_stake_amount, 1e-8),
                max(-5.0, min(5.0, leveraged_return)),
                position_age / max(self.window_size, 1.0),
                closed_trades / max(episode_step, 1),
            ],
            dtype=torch.float32,
        )

        obs = torch.cat(
            [
                torch.tensor(feature_window, dtype=torch.float32),
                self._normalized_action_history(action_history),
                self._config_vector(),
                state_features,
            ],
            dim=0,
        )
        return obs.to(self._device)

    def _infer_action_from_obs(self, obs: torch.Tensor) -> float:
        """对单条观测做 policy 推理，并把异常输出压回安全中立范围。"""
        if self._policy is None:
            return self.neutral_action_value

        with torch.inference_mode():
            try:
                raw_action = self._policy(obs.unsqueeze(0))
            except RuntimeError as exc:
                if not self._warned_policy_shape_mismatch:
                    logger.warning(
                        "RL policy input shape mismatch. The market feature set changed, "
                        "so retrain policy.pt before live use. Falling back to neutral. Error: %s",
                        exc,
                    )
                    self._warned_policy_shape_mismatch = True
                return self.neutral_action_value
            action_value = float(raw_action.squeeze().item())

        if not np.isfinite(action_value):
            return self.neutral_action_value
        return float(np.clip(action_value, 0.0, 1.0))

    def _predict_action_at(
        self,
        dataframe: DataFrame,
        current_index: int,
        *,
        trade=None,
        current_time: datetime | None = None,
        current_rate: float | None = None,
        action_history: Iterable[float] | None = None,
    ) -> float:
        """在指定 dataframe 索引处推理动作。

        populate_entry_trend 会逐根 K 线调用这个方法，避免一次性只看最后一根。
        """
        if self._policy is None or len(dataframe) < self.window_size:
            return self.neutral_action_value

        last_mid = float(dataframe["mid"].iloc[current_index])
        if last_mid <= 0:
            return self.neutral_action_value

        obs = self._build_observation(
            dataframe,
            current_index,
            trade=trade,
            current_time=current_time,
            current_rate=current_rate,
            action_history=action_history,
        )
        return self._infer_action_from_obs(obs)

    def _predict_action(
        self,
        dataframe: DataFrame,
        *,
        trade=None,
        current_time: datetime | None = None,
        current_rate: float | None = None,
    ) -> float:
        """对当前可见 dataframe 的最后一根 K 线推理动作，主要用于持仓退出。"""
        history = self._action_history_from_frame(dataframe)
        return self._predict_action_at(
            dataframe,
            len(dataframe) - 1,
            trade=trade,
            current_time=current_time,
            current_rate=current_rate,
            action_history=history,
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算训练环境和实盘共同使用的归一化市场特征。"""
        return add_market_features(dataframe)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """生成入场信号。

        这里直接用 RL 输出决定 enter_long / enter_short，不再同时打多空标记；
        同一根 K 线同时多空会被 Freqtrade 判定为信号冲突。
        """
        dataframe.loc[:, ["enter_long", "enter_short", "enter_tag"]] = (0, 0, "")
        dataframe.loc[:, "rl_action"] = self.neutral_action_value
        dataframe.loc[:, "rl_signal"] = "neutral"

        if len(dataframe) < self.startup_candle_count:
            return dataframe

        history = deque(
            [self.neutral_action_value] * self.action_history_size,
            maxlen=self.action_history_size,
        )

        # 回测时需要逐根生成动作历史；否则每一根都用全 0.5 历史，会和训练环境脱节。
        for current_index in range(self.window_size - 1, len(dataframe)):
            action_value = self._predict_action_at(dataframe, current_index, action_history=history)
            signal = self._action_to_signal(action_value)
            dataframe.iat[current_index, dataframe.columns.get_loc("rl_action")] = action_value
            dataframe.iat[current_index, dataframe.columns.get_loc("rl_signal")] = signal
            history.append(action_value)

        long_mask = dataframe["rl_signal"] == "long"
        short_mask = dataframe["rl_signal"] == "short"
        dataframe.loc[long_mask, ["enter_long", "enter_tag"]] = (1, "rl_long")
        dataframe.loc[short_mask, ["enter_short", "enter_tag"]] = (1, "rl_short")
        return dataframe

    def _latest_signal(self, dataframe: DataFrame, current_time=None) -> tuple[float, str]:
        """读取当前时间可见的最新 RL 信号。"""
        dataframe = self._dataframe_until(dataframe, current_time)
        if dataframe is None or len(dataframe) < self.startup_candle_count:
            return self.neutral_action_value, "neutral"

        last = dataframe.iloc[-1]
        action_value = float(last.get("rl_action", self.neutral_action_value))
        if not np.isfinite(action_value):
            action_value = self.neutral_action_value
        signal = str(last.get("rl_signal", self._action_to_signal(action_value)))
        return float(np.clip(action_value, 0.0, 1.0)), signal

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        """最终确认入场。

        populate_entry_trend 已经生成方向，这里再用当前时间可见的最新信号做一道保护。
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        action_value, signal = self._latest_signal(dataframe, current_time)
        candle_date = self._current_candle_date(current_time)
        entry_key = (pair, side)
        already_entered = candle_date is not None and self._last_entry_candle_by_pair.get(entry_key) == candle_date
        pair_locked = self.is_pair_locked(pair, candle_date=current_time, side=side)
        allowed = signal == side and not already_entered and not pair_locked
        if allowed and candle_date is not None:
            self._last_entry_candle_by_pair[entry_key] = candle_date

        logger.info(
            f"{pair} RL confirm_entry: action={action_value:.4f} -> {signal}, "
            f"side={side}, candle={candle_date}, already_entered={already_entered}, "
            f"pair_locked={pair_locked}, allowed={allowed}"
        )
        return allowed

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """根据 RL 信号决定是否允许下注。

        返回 0 会取消本次入场；允许入场时按训练资金规模限制保证金，避免测试网大余额放大仓位。
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        _action_value, signal = self._latest_signal(dataframe, current_time)
        if signal != side:
            return 0

        target_stake = self.rl_stake_amount * self.tradable_balance_ratio
        return max(0.0, min(proposed_stake, max_stake, target_stake))

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | bool | None:
        """净利润止盈逻辑。

        action 只负责入场方向，不参与平仓。这里仅用 Freqtrade 传入的
        current_profit 做一道扣费后 1% 止盈保护；10% 止损由 stoploss 处理。
        """
        if current_profit >= self.minimal_roi_rl:
            return "net_take_profit"
        return None

    def confirm_trade_exit(
        self,
        pair: str,
        trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time,
        **kwargs,
    ) -> bool:
        """允许所有已触发的退出。

        是否触发退出交给 custom_exit、ROI 和 stoploss；这里不再二次拦截，
        避免止盈止损被 RL 信号误挡。
        """
        return True

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """返回策略期望杠杆，但不超过交易所允许的最大杠杆。"""
        return min(self.leverage_value, max_leverage)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """保留退出列，主动退出由 custom_exit 完成。"""
        dataframe.loc[:, ["exit_long", "exit_short", "exit_tag"]] = (0, 0, "")
        return dataframe
