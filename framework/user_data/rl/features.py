from __future__ import annotations

# 导入 NumPy，用于数值计算和异常值处理。
import numpy as np

# 导入 pandas，用于处理行情表和滚动统计。
import pandas as pd


# 定义需要输出的市场特征列名。
MARKET_FEATURE_COLUMNS: tuple[str, ...] = (
    # 普通收益率。
    "returns",
    # 对数收益率。
    "log_returns",
    # 成交量比例。
    "volume_ratio",
    # RSI 特征。
    "rsi_14",
    # MACD 主线。
    "macd",
    # MACD 信号线。
    "macd_signal",
    # MACD 柱状图。
    "macd_hist",
    # 20 周期 EMA 比例。
    "ema_20_ratio",
    # 50 周期 EMA 比例。
    "ema_50_ratio",
    # 波动率标准分数。
    "volatility",
    # 趋势强度。
    "trend_strength",
    # 波动率制度。
    "vol_regime",
)


# 为输入行情表添加市场特征。
def add_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    # 返回给训练和实时推理共用的标准化市场特征。
    # 原始价格不会直接送入策略，避免输入分布过于不稳定。
    # 特征使用收益率、比例和有界振荡指标表示，以增强平稳性。
    frame = frame.copy()
    # 提取并清洗收盘价，避免后续出现零或无效值。
    close = frame["close"].astype(float).clip(lower=1e-8)
    # 提取并清洗成交量，避免负值进入后续计算。
    volume = frame["volume"].astype(float).clip(lower=0.0)

    # 计算中间价，作为额外的辅助特征。
    frame["mid"] = (frame["high"].astype(float) + frame["low"].astype(float)) / 2.0

    # 计算普通收益率并清理无穷值和缺失值。
    returns = close.pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    # 计算对数收益率并清理无穷值和缺失值。
    log_returns = np.log(close).diff().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    # 将普通收益率截断到较小范围，减少极端值影响。
    frame["returns"] = returns.clip(-0.1, 0.1)
    # 将对数收益率截断到较小范围，减少极端值影响。
    frame["log_returns"] = log_returns.clip(-0.1, 0.1)

    # 计算成交量滚动均值，并把零值替换为 NaN 以便后续处理。
    volume_mean = volume.rolling(30, min_periods=1).mean().replace(0.0, np.nan)
    # 计算成交量相对均值的对数比例，并清理异常值。
    frame["volume_ratio"] = np.log(volume / volume_mean + 1e-8).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-5.0, 5.0)

    # 计算价格变化量。
    delta = close.diff().fillna(0.0)
    # 计算 RSI 的上涨部分。
    gain = delta.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False).mean()
    # 计算 RSI 的下跌部分。
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    # 计算相对强弱值，并避免除以零。
    rs = gain / loss.replace(0.0, np.nan)
    # 计算 RSI，并用中性值 50 填补缺失。
    rsi = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)
    # 将 RSI 归一化到 -1 到 1 区间。
    frame["rsi_14"] = ((rsi - 50.0) / 50.0).clip(-1.0, 1.0)

    # 计算 12 周期 EMA。
    ema_12 = close.ewm(span=12, adjust=False).mean()
    # 计算 26 周期 EMA。
    ema_26 = close.ewm(span=26, adjust=False).mean()
    # 计算 MACD 原始主线值。
    macd_raw = ema_12 - ema_26
    # 计算 MACD 信号线原始值。
    macd_signal_raw = macd_raw.ewm(span=9, adjust=False).mean()
    # 计算 MACD 柱状图原始值。
    macd_hist_raw = macd_raw - macd_signal_raw
    # 将 MACD 主线按价格归一化并裁剪。
    frame["macd"] = (macd_raw / close).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)
    # 将 MACD 信号线按价格归一化并裁剪。
    frame["macd_signal"] = (macd_signal_raw / close).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)
    # 将 MACD 柱状图按价格归一化并裁剪。
    frame["macd_hist"] = (macd_hist_raw / close).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)

    # 计算 20 周期 EMA。
    ema_20 = close.ewm(span=20, adjust=False).mean()
    # 计算 50 周期 EMA。
    ema_50 = close.ewm(span=50, adjust=False).mean()
    # 计算价格相对 20 周期 EMA 的偏离比例。
    frame["ema_20_ratio"] = (close / ema_20 - 1.0).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)
    # 计算价格相对 50 周期 EMA 的偏离比例。
    frame["ema_50_ratio"] = (close / ema_50 - 1.0).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)
    # 计算短期与长期均线之间的趋势强度。
    frame["trend_strength"] = ((ema_20 - ema_50) / close).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-0.2, 0.2)

    # 计算短期实现波动率。
    realized_vol = log_returns.rolling(30, min_periods=2).std().fillna(0.0)
    # 计算实现波动率的中期均值。
    vol_mean = realized_vol.rolling(1200, min_periods=10).mean()
    # 计算实现波动率的中期标准差，并避免零除。
    vol_std = realized_vol.rolling(1200, min_periods=10).std().replace(0.0, np.nan)
    # 将波动率标准化并裁剪到有限区间。
    frame["volatility"] = ((realized_vol - vol_mean) / vol_std).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-5.0, 5.0)

    # 计算长期波动率，用于识别波动率制度。
    long_vol = log_returns.rolling(1200, min_periods=10).std().replace(0.0, np.nan)
    # 计算短期和长期波动率的对数比值。
    frame["vol_regime"] = np.log(realized_vol / long_vol + 1e-8).replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-5.0, 5.0)
    # 对所有市场特征列统一清理无穷值和缺失值。
    frame.loc[:, MARKET_FEATURE_COLUMNS] = frame.loc[:, MARKET_FEATURE_COLUMNS].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    # 返回补充完特征的数据表。
    return frame
