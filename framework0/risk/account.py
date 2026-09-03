from dataclasses import dataclass  # 用 dataclass 简化账户收益数据结构


@dataclass  # 自动生成初始化方法，方便保存账户字段
class Account:  # 定义模拟账户对象，用来记录余额和收益
    initial_balance: float  # 初始账户余额，单位 USDT
    balance: float  # 当前账户余额，单位 USDT
    realized_pnl: float = 0.0  # 累计已实现盈亏，单位 USDT
    fees_paid: float = 0.0  # 累计手续费，单位 USDT

    @property  # 把收益率做成只读属性，访问时自动计算
    def return_pct(self) -> float:  # 定义账户收益率
        if self.initial_balance == 0:  # 如果初始余额为 0，避免除以 0
            return 0.0  # 返回 0 收益率
        return self.realized_pnl / self.initial_balance  # 收益率 = 累计盈亏 / 初始余额

    def apply_pnl(self, pnl_usdt: float) -> None:  # 定义函数：把一笔平仓盈亏计入账户
        self.realized_pnl += pnl_usdt  # 更新累计已实现盈亏
        self.balance += pnl_usdt  # 更新账户当前余额

    def apply_fee(self, fee_usdt: float) -> None:  # 定义函数：把一笔手续费计入账户
        self.fees_paid += fee_usdt  # 更新累计手续费
        self.realized_pnl -= fee_usdt  # 手续费视为已实现亏损
        self.balance -= fee_usdt  # 更新账户当前余额
