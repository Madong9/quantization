from __future__ import annotations  # 启用未来注解语法，便于使用更现代的类型标注。

import math  # 提供 log，用于计算归一化权益收益奖励。
from collections import deque  # 提供双端队列，用于保存最近的动作历史。
from dataclasses import dataclass  # 提供 dataclass 装饰器，方便定义状态结构。
from pathlib import Path  # 提供跨平台路径对象。
from typing import Deque  # 提供动作历史队列的类型标注。

import pandas as pd  # type: ignore  # 提供 DataFrame 读取和处理能力。
import torch  # type: ignore  # 提供张量运算能力。
from tensordict import TensorDict  # type: ignore  # 提供 rsl_rl 需要的 TensorDict 观测容器。

from rsl_rl.env import VecEnv  # type: ignore  # 导入 rsl_rl 的并行环境基类。

from .config import RslPpoTradingConfig  # 导入 RL 配置结构。
from .features import MARKET_FEATURE_COLUMNS, add_market_features  # 导入训练/实盘共享的市场特征。


STATE_FEATURE_DIM = 10  # 持仓/账户状态特征维度，训练环境和实盘策略需要保持一致。


def load_market_frame(path: str | Path) -> pd.DataFrame:  # 读取并整理行情数据。
    frame = pd.read_feather(path)  # 从 feather 文件读取行情数据。
    if "date" in frame.columns:  # 如果数据里有时间列，就先按时间排序。
        frame = frame.sort_values("date")  # 确保 K 线顺序正确。
    frame = frame.reset_index(drop=True).copy()  # 重置索引并复制一份干净的数据表。
    return add_market_features(frame)  # 添加归一化市场特征后返回。


@dataclass  # 把单个环境实例的交易状态封装成数据类。
class TradingState:  # 记录每个并行环境当前的交易状态。
    current_index: int  # 当前所在的行情索引。
    episode_step: int  # 当前 episode 已走的步数。
    cash_balance: float  # 当前可用现金余额。
    position_side: int  # 持仓方向，1 表示多，-1 表示空，0 表示空仓。
    entry_price: float  # 持仓开仓价格。
    position_quantity: float  # 持仓数量。
    position_notional: float  # 持仓名义价值。
    position_age: int  # 当前持仓已经持有了多少步。
    total_fees_paid: float  # 累计手续费。
    closed_trades: int  # 已平仓交易次数。
    winning_trades: int  # 盈利平仓次数。
    gross_profit: float  # 未扣手续费前的累计毛利润。
    max_equity: float  # 迄今为止达到的最高权益。
    action_history: Deque[float]  # 最近动作历史队列。


class RslTradingVecEnv(VecEnv):  # 基于 rsl_rl 的并行交易环境。
    def __init__(
        self,  # 当前对象本身。
        market_frame: pd.DataFrame,  # 输入的行情数据表。
        cfg: RslPpoTradingConfig,  # RL 配置对象。
        num_envs: int = 4096,  # 并行环境数量。
        device: str = "cpu",  # 运行设备。
    ) -> None:  # 初始化完成，不返回值。
        self.market = add_market_features(market_frame.reset_index(drop=True).copy())  # 复制行情并计算共享特征。
        required_columns = {"open", "high", "low", "close"}  # 定义行情必须具备的列。
        missing = required_columns.difference(self.market.columns)  # 找出缺失列。
        if missing:  # 如果有缺失列。
            raise ValueError(f"market_frame missing columns: {sorted(missing)}")  # 直接报错。

        self.mids = torch.tensor(self.market["mid"].to_numpy(), dtype=torch.float32)  # 将中值价格转成张量，放在CPU上便于快速索引（环境模拟无法被GPU加速）。
        self.market_features = torch.tensor(
            self.market.loc[:, MARKET_FEATURE_COLUMNS].to_numpy(),
            dtype=torch.float32,
        )  # 将归一化市场特征转成张量，避免给 policy 直接喂 raw close/mid。
        self.cfg = cfg.to_dict()  # 保存可序列化的配置字典，供 rsl_rl logger 使用。
        self.trading_cfg = cfg  # 保存原始配置对象，便于后续计算。
        self.num_envs = num_envs  # 设置并行环境数量。
        self.num_actions = 1  # 动作空间维度为 1 个连续动作值，0.5 表示中立。
        self.device = torch.device(device)  # 将设备字符串转成 torch.device。
        self.max_episode_length = int(cfg.episode_length)  # 设置每个 episode 的最长步数。
        self.episode_length_buf = torch.zeros(self.num_envs, dtype=torch.long, device=self.device)  # 记录每个环境当前 episode 长度。
        self.neutral_action_value = 0.50  # 动作历史的冷启动值。
        self.short_action_threshold = float(cfg.short_action_threshold)  # 动作低于该阈值时开空。
        self.long_action_threshold = float(cfg.long_action_threshold)  # 动作高于该阈值时开多，中间区间观望。
        if not 0.0 <= self.short_action_threshold < self.long_action_threshold <= 1.0:  # 校验动作分段是否合法。
            raise ValueError("short_action_threshold must be < long_action_threshold and both must be within [0, 1]")
        self._obs_dim = cfg.window_size * len(MARKET_FEATURE_COLUMNS) + cfg.action_history_size + len(cfg.to_vector()) + STATE_FEATURE_DIM  # 计算观测向量总长度。
        self._max_start_index = max(cfg.window_size, len(self.mids) - cfg.episode_length - 2)  # 计算 episode 起始索引上限。
        self._states = [self._new_state() for _ in range(self.num_envs)]  # 为每个并行环境初始化独立状态。

    def _sample_start_index(self) -> int:  # 随机采样一个 episode 起点。
        if self._max_start_index <= self.trading_cfg.window_size:  # 如果数据长度不足以随机采样。
            return self.trading_cfg.window_size  # 直接从最小安全索引开始。
        return int(torch.randint(self.trading_cfg.window_size, self._max_start_index + 1, (1,)).item())  # 否则随机取一个起点。

    def _new_state(self) -> TradingState:  # 创建一个新的交易状态对象。
        start_index = self._sample_start_index()  # 采样新的 episode 起点。
        return TradingState(  # 返回初始化好的状态。
            current_index=start_index,  # 当前索引从随机起点开始。
            episode_step=0,  # 初始步数为 0。
            cash_balance=self.trading_cfg.stake_amount,  # 初始现金余额等于模拟钱包金额。
            position_side=0,  # 初始为空仓。
            entry_price=0.0,  # 初始没有开仓价。
            position_quantity=0.0,  # 初始没有持仓数量。
            position_notional=0.0,  # 初始持仓名义价值为 0。
            position_age=0,  # 初始持仓年龄为 0。
            total_fees_paid=0.0,  # 初始手续费累计为 0。
            closed_trades=0,  # 初始平仓次数为 0。
            winning_trades=0,  # 初始盈利次数为 0。
            gross_profit=0.0,  # 初始毛利润为 0。
            max_equity=self.trading_cfg.stake_amount,  # 初始最高权益等于初始资金。
            action_history=deque([self.neutral_action_value] * self.trading_cfg.action_history_size, maxlen=self.trading_cfg.action_history_size),  # 用中立动作初始化历史。
        )  # 结束状态构造。

    def _action_to_side(self, action_value: float) -> int:  # 将连续动作映射成持仓方向。
        if action_value < self.short_action_threshold:  # 如果动作值落在低区间。
            return -1  # 映射为空头目标。
        if action_value > self.long_action_threshold:  # 如果动作值落在高区间。
            return 1  # 映射为多头目标。
        return 0  # 中间区间表示观望；已有持仓保持不变，空仓不新开仓。

    def _portfolio_value(self, state: TradingState, price: float) -> float:  # 计算当前权益。
        if state.position_side == 0:  # 如果当前是空仓。
            return state.cash_balance  # 权益就是现金余额。
        unrealized = state.position_side * state.position_quantity * (price - state.entry_price)  # 计算未实现盈亏。
        return state.cash_balance + unrealized  # 返回现金加未实现盈亏后的总权益。

    def _open_position(self, state: TradingState, side: int, price: float) -> float:  # 按当前价格开一个新仓位。
        state.position_side = side  # 记录开仓方向。
        state.entry_price = price  # 记录开仓价格。
        state.position_notional = state.cash_balance * self.trading_cfg.tradable_balance_ratio * self.trading_cfg.leverage  # 计算名义价值。
        state.position_quantity = state.position_notional / max(price, 1e-8)  # 根据价格换算成持仓数量。
        fee = state.position_notional * self.trading_cfg.fee_rate  # 计算开仓手续费。
        state.cash_balance -= fee  # 从现金中扣除手续费。
        return fee  # 返回这次开仓手续费。

    def _close_position(self, state: TradingState, price: float) -> tuple[bool, bool, float]:  # 平掉当前持仓并结算盈亏。
        if state.position_side == 0:  # 如果当前没有持仓。
            return False, False, 0.0  # 直接返回没有发生平仓。

        close_fee = state.position_notional * self.trading_cfg.fee_rate  # 计算平仓手续费。
        gross_pnl = state.position_side * state.position_quantity * (price - state.entry_price)  # 计算毛盈亏。
        net_pnl = gross_pnl - close_fee  # 扣除平仓手续费后的净盈亏。
        state.cash_balance += net_pnl  # 将净盈亏计入现金余额。
        state.gross_profit += gross_pnl  # 累积毛利润。
        state.closed_trades += 1  # 平仓次数加 1。
        was_win = net_pnl > 0.0  # 判断这笔交易是否盈利。
        if was_win:  # 如果这笔交易是盈利单。
            state.winning_trades += 1  # 盈利次数加 1。

        state.position_side = 0  # 平仓后重置方向。
        state.entry_price = 0.0  # 平仓后重置开仓价。
        state.position_quantity = 0.0  # 平仓后重置持仓数量。
        state.position_notional = 0.0  # 平仓后重置名义价值。
        state.position_age = 0  # 平仓后重置持仓年龄。
        return True, was_win, close_fee  # 返回是否平仓、是否盈利、平仓手续费。

    def _net_return_after_fees(self, state: TradingState, price: float) -> float:  # 计算扣除开平仓手续费后的持仓收益率。
        if state.position_side == 0:  # 空仓没有持仓收益。
            return 0.0  # 返回零收益。

        gross_pnl = state.position_side * state.position_quantity * (price - state.entry_price)  # 计算毛盈亏。
        round_trip_fees = state.position_notional * self.trading_cfg.fee_rate * 2.0  # 估算开仓和平仓总手续费。
        margin = state.position_notional / max(self.trading_cfg.leverage, 1e-8)  # 用保证金作为收益率分母。
        return (gross_pnl - round_trip_fees) / max(margin, 1e-8)  # 返回扣费后的交易收益率。

    def _auto_exit_if_needed(self, state: TradingState, price: float) -> tuple[bool, bool, float]:  # 根据止盈止损自动平仓。
        if state.position_side == 0:  # 空仓时不需要自动退出。
            return False, False, 0.0  # 直接返回没有平仓。

        net_return = self._net_return_after_fees(state, price)  # 计算扣除开平仓手续费后的收益率。
        if net_return >= self.trading_cfg.minimal_roi or net_return <= self.trading_cfg.stoploss:  # 检查是否达到止盈或止损。
            return self._close_position(state, price)  # 满足条件就直接平仓。
        return False, False, 0.0  # 否则不操作。

    def _compute_reward(
        self,
        state: TradingState,
        target_side: int,
        portfolio_before: float,
        portfolio_after: float,
        fees_paid: float,
        drawdown: float,
        closed_trade: bool,
        closed_trade_was_win: bool,
    ) -> float:  # 计算单步奖励。
        equity_floor = max(self.trading_cfg.stake_amount * 1e-6, 1e-8)  # 防止权益归零导致 log 无定义。
        safe_before = max(portfolio_before, equity_floor)  # 将分母限制在安全范围内。
        safe_after = max(portfolio_after, equity_floor)  # 将分子限制在安全范围内。
        reward = math.log(safe_after / safe_before) * self.trading_cfg.reward_equity_scale  # 用 log return 归一化权益变化。

        if fees_paid > 0.0:  # 手续费已经体现在权益里，这里只额外给一个轻量交易成本偏置。
            reward -= self.trading_cfg.reward_fee_weight * (fees_paid / safe_before)
        if target_side == 0 and state.position_side == 0 and not closed_trade:  # 空仓继续观望时给极小惩罚，避免永远不交易。
            reward -= self.trading_cfg.reward_flat_penalty
        if closed_trade:  # 平仓时给轻量胜负反馈，帮助 credit assignment。
            reward += self.trading_cfg.reward_closed_trade_bonus if closed_trade_was_win else -self.trading_cfg.reward_closed_trade_bonus
        if drawdown > 0.0:  # 对回撤给归一化惩罚。
            reward -= drawdown * self.trading_cfg.reward_drawdown_weight

        clip = self.trading_cfg.reward_clip  # 读取奖励裁剪范围。
        return max(-clip, min(clip, reward))  # 裁剪单步奖励，避免破产步产生极端优势值。

    def _build_observation(self, state: TradingState) -> torch.Tensor:  # 拼接单个环境的观测向量。
        start = state.current_index - self.trading_cfg.window_size + 1  # 计算回看窗口起始位置。
        feature_window = self.market_features[start : state.current_index + 1].flatten()  # 取最近窗口的归一化市场特征。
        reference_price = torch.clamp(self.mids[state.current_index], min=1e-8)  # 当前 mid 只用于持仓权益和入场偏移。

        action_history = torch.tensor(list(state.action_history), dtype=torch.float32)  # 把动作历史转成张量。
        config_vector = torch.tensor(self.trading_cfg.to_vector(), dtype=torch.float32)  # 把配置向量转成张量。
        portfolio_value = self._portfolio_value(state, float(reference_price))  # 计算当前权益。
        current_price = float(reference_price)  # 转成 Python float，后面统一计算持仓状态。
        unrealized_pnl = state.position_side * state.position_quantity * (current_price - state.entry_price) if state.position_side != 0 else 0.0  # 当前未实现盈亏。
        leveraged_return = (
            state.position_side * ((current_price - state.entry_price) / max(state.entry_price, 1e-8)) * self.trading_cfg.leverage
            if state.position_side != 0
            else 0.0
        )  # 当前持仓杠杆收益率。
        state_features = torch.tensor(  # 构造状态特征向量。
            [  # 下面依次是方向、入场偏移、现金比、权益比、数量、名义价值比、未实现盈亏比、杠杆收益率、持仓年龄、平仓密度。
                float(state.position_side),  # 当前持仓方向。
                float(state.entry_price) / current_price - 1.0 if state.position_side != 0 else 0.0,  # 入场价相对偏移。
                state.cash_balance / max(self.trading_cfg.stake_amount, 1e-8),  # 现金余额比例。
                portfolio_value / max(self.trading_cfg.stake_amount, 1e-8),  # 总权益比例。
                state.position_quantity,  # 当前持仓数量。
                state.position_notional / max(self.trading_cfg.stake_amount, 1e-8),  # 当前持仓名义价值比例。
                unrealized_pnl / max(self.trading_cfg.stake_amount, 1e-8),  # 当前未实现盈亏比例。
                max(-5.0, min(5.0, leveraged_return)),  # 当前杠杆收益率，限制极端值。
                state.position_age / max(self.trading_cfg.window_size, 1.0),  # 持仓年龄归一化。
                state.closed_trades / max(state.episode_step, 1),  # 当前 episode 内平仓密度。
            ],  # 状态特征列表结束。
            dtype=torch.float32,  # 指定浮点类型。
        )  # 状态特征张量构造完成。
        return torch.cat(  # 将所有特征拼成最终观测。
            [feature_window.to(torch.float32), action_history, config_vector, state_features],  # 按顺序拼接各部分特征。
            dim=0,  # 在特征维拼接。
        )  # 返回最终观测张量（在CPU上）。

    def _build_info(
        self,
        state: TradingState,
        reward: float,
        fees_paid: float,
        closed_trade: bool,
        no_trade_action: bool,
        equity_stop: bool,
    ) -> dict[str, torch.Tensor]:  # 生成日志信息。
        win_rate = state.winning_trades / max(state.closed_trades, 1)  # 计算当前胜率。
        return {  # 返回给 logger 的信息字典。
            "/rl/reward": torch.tensor(reward, dtype=torch.float32),  # 当前步奖励。
            "/rl/fees_paid": torch.tensor(fees_paid, dtype=torch.float32),  # 当前步手续费。
            "/rl/closed_trade": torch.tensor(float(closed_trade), dtype=torch.float32),  # 是否发生平仓。
            "/rl/no_trade_action": torch.tensor(float(no_trade_action), dtype=torch.float32),  # 当前动作是否落在观望区间。
            "/rl/equity_stop": torch.tensor(float(equity_stop), dtype=torch.float32),  # 是否因权益过低结束 episode。
            "/rl/win_rate": torch.tensor(win_rate, dtype=torch.float32),  # 当前胜率。
            "/rl/portfolio_value": torch.tensor(self._portfolio_value(state, float(self.mids[state.current_index])), dtype=torch.float32),  # 当前权益。
            "/rl/closed_trades": torch.tensor(float(state.closed_trades), dtype=torch.float32),  # 已平仓次数。
            "/rl/total_fees_paid": torch.tensor(float(state.total_fees_paid), dtype=torch.float32),  # 累计手续费。
        }  # 结束日志信息字典。

    def _reset_state(self, idx: int) -> None:  # 重置某个并行环境的状态。
        self._states[idx] = self._new_state()  # 重新生成一个新状态。
        self.episode_length_buf[idx] = 0  # 清零该环境的 episode 长度缓存。

    def get_observations(self) -> TensorDict:  # 返回当前所有环境的观测。
        obs = torch.stack([self._build_observation(state) for state in self._states], dim=0)  # 堆叠并行观测张量（在CPU上）。
        obs = obs.to(self.device)  # 批量移动到GPU/device，单次PCIe传输比多次高效。
        return TensorDict({"policy": obs}, batch_size=[self.num_envs], device=self.device)  # 用 TensorDict 包装成 rsl_rl 需要的格式。

    def step(self, actions: torch.Tensor) -> tuple[TensorDict, torch.Tensor, torch.Tensor, dict]:  # 执行一步环境交互。
        actions = actions.to(self.device)  # 把动作移动到当前设备。
        if actions.ndim == 1:  # 如果只有一维，就补一个动作维度。
            actions = actions.unsqueeze(-1)  # 扩展成二维张量。
        actions = actions.view(self.num_envs, -1)  # 整理成 [num_envs, action_dim] 形状。

        rewards = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)  # 初始化奖励张量。
        dones = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)  # 初始化 done 标记张量。
        time_outs = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)  # 初始化超时标记张量。
        log_keys = ["/rl/reward", "/rl/fees_paid", "/rl/win_rate", "/rl/portfolio_value", "/rl/closed_trades", "/rl/no_trade_action", "/rl/equity_stop"]  # 需要聚合记录的日志键。
        log_accumulator: dict[str, list[torch.Tensor]] = {key: [] for key in log_keys}  # 为每个日志键准备累积容器。

        next_states: list[TradingState] = []  # 存放每个环境下一时刻的状态。
        next_obs: list[torch.Tensor] = []  # 存放每个环境下一时刻的观测。

        for env_idx, state in enumerate(self._states):  # 遍历每个并行环境。
            action_value = float(torch.clamp(actions[env_idx, 0], 0.0, 1.0).item())  # 取出该环境的动作并限制在 0 到 1。
            state.action_history.append(action_value)  # 记录动作到历史队列。

            current_price = float(self.mids[state.current_index].item())  # 取当前中值价格。
            portfolio_before = self._portfolio_value(state, current_price)  # 记录动作前的权益。
            fees_paid = 0.0  # 初始化当前步手续费。
            closed_trade = False  # 初始化当前步是否发生平仓。
            closed_trade_was_win = False  # 初始化平仓是否盈利。

            target_side = self._action_to_side(action_value)  # 将动作映射成目标持仓方向。
            no_trade_action = target_side == 0  # 中间动作区间表示观望。
            if state.position_side == 0 and target_side != 0:  # action 只负责空仓时开仓，不负责平仓或反手。
                fees_paid += self._open_position(state, target_side, current_price)  # 按目标方向开新仓。

            if state.position_side != 0:  # 如果当前仍然持仓。
                state.position_age += 1  # 持仓年龄加 1。

            next_index = min(state.current_index + 1, len(self.mids) - 1)  # 计算下一步索引，并避免越界。
            next_price = float(self.mids[next_index].item())  # 取下一步价格。
            auto_close, auto_win, auto_close_fee = self._auto_exit_if_needed(state, next_price)  # 检查是否要自动平仓。
            fees_paid += auto_close_fee  # 累计自动平仓手续费。
            if auto_close:  # 如果触发了止盈或止损平仓。
                closed_trade = True  # 标记发生了平仓。
                closed_trade_was_win = auto_win  # 记录这次平仓是否盈利。

            portfolio_after = self._portfolio_value(state, next_price)  # 计算动作后的权益。
            state.max_equity = max(state.max_equity, portfolio_after)  # 更新历史最高权益。
            drawdown = max(0.0, (state.max_equity - portfolio_after) / max(state.max_equity, 1e-8))  # 计算当前回撤。
            reward = self._compute_reward(  # 通过单独函数计算奖励，便于后续单测和调参。
                state,  # 当前状态。
                target_side,  # 目标持仓方向。
                portfolio_before,  # 动作前权益。
                portfolio_after,  # 动作后权益。
                fees_paid,  # 当前步手续费。
                drawdown,  # 当前回撤。
                closed_trade,  # 是否发生平仓。
                closed_trade_was_win,  # 平仓是否盈利。
            )  # 结束奖励计算调用。

            state.total_fees_paid += fees_paid  # 累计手续费。
            state.current_index = next_index  # 推进到下一根 K 线。
            state.episode_step += 1  # episode 步数加 1。
            self.episode_length_buf[env_idx] = state.episode_step  # 更新缓冲中的 episode 长度。

            log_state = state  # 保存当前步的状态快照用于日志。
            equity_stop = portfolio_after <= self.trading_cfg.stake_amount * self.trading_cfg.min_equity_ratio  # 权益过低时提前结束，避免继续在破产状态采样。
            time_limit_stop = state.episode_step >= self.max_episode_length or state.current_index >= len(self.mids) - 1  # 判断是否达到时间/数据边界。
            done = equity_stop or time_limit_stop  # 任一终止条件满足就结束当前 episode。
            if done:  # 如果 episode 结束。
                dones[env_idx] = 1.0  # 设置 done 标记。
                time_outs[env_idx] = 0.0 if equity_stop else 1.0  # 低权益是失败终止，不做 timeout bootstrap。
                self._reset_state(env_idx)  # 重置该环境状态。
                state = self._states[env_idx]  # 取出重置后的新状态。
                self.episode_length_buf[env_idx] = 0  # 清零长度缓冲。
            next_states.append(state)  # 保存下一时刻状态。
            next_obs.append(self._build_observation(state))  # 生成下一时刻观测。
            rewards[env_idx] = reward  # 记录该环境的奖励。
            log_info = self._build_info(log_state, reward, fees_paid, closed_trade, no_trade_action, equity_stop)  # 生成日志信息。
            for key in log_keys:  # 遍历所有需要聚合的日志键。
                log_accumulator[key].append(log_info[key])  # 将当前值加入聚合容器。

        self._states = next_states  # 用更新后的状态列表替换旧状态。
        obs_tensor = torch.stack(next_obs, dim=0)  # 将下一时刻观测堆叠成批量张量（在CPU上）。
        obs_tensor = obs_tensor.to(self.device)  # 批量移动到GPU/device，单次PCIe传输而不是多次。
        extras = {  # 构造 rsl_rl 需要的额外信息字典。
            "time_outs": time_outs,  # 提供超时标记，用于奖励 bootstrap。
            "log": {key: torch.stack(values).mean() for key, values in log_accumulator.items()},  # 对日志值取均值后输出。
        }  # 结束 extras 字典。
        return TensorDict({"policy": obs_tensor}, batch_size=[self.num_envs], device=self.device), rewards, dones, extras  # 返回观测、奖励、结束标记和额外信息。
