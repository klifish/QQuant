"""
技术指标计算模块。

所有函数接收单只股票的 DataFrame（按 trade_date 升序排列），
返回添加了指标列的新 DataFrame。不修改原始数据。

严防未来函数：指标计算只用当前行及之前的历史数据。
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 移动平均线
# ---------------------------------------------------------------------------

def calc_ma(df: pd.DataFrame, windows: list[int] = (10, 20, 60)) -> pd.DataFrame:
    """
    计算多周期简单移动平均，使用前复权收盘价（close_qfq）。
    新增列：ma10, ma20, ma60（或其他指定窗口）
    """
    df = df.copy()
    price_col = "close_qfq" if "close_qfq" in df.columns else "close"
    for w in windows:
        df[f"ma{w}"] = df[price_col].rolling(w, min_periods=w).mean()
    return df


def calc_ma_slope(df: pd.DataFrame, ma_col: str = "ma20") -> pd.DataFrame:
    """
    计算均线方向（今日均线 > 昨日均线 → 向上）。
    新增布尔列：{ma_col}_up
    """
    df = df.copy()
    df[f"{ma_col}_up"] = df[ma_col] > df[ma_col].shift(1)
    return df


# ---------------------------------------------------------------------------
# 突破信号
# ---------------------------------------------------------------------------

def calc_breakout(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    计算 N 日最高价突破信号：当日收盘价 > 过去 N 日最高价（不含当日）。

    注意：使用 shift(1) 确保不包含当日，严防未来函数。
    新增列：
      high_{window}d   — 过去 N 日最高价（不含当日）
      breakout_{window}d — 布尔，当日收盘价是否突破
    """
    df = df.copy()
    price_col = "close_qfq" if "close_qfq" in df.columns else "close"
    high_col = "high_qfq" if "high_qfq" in df.columns else "high"

    past_high = df[high_col].shift(1).rolling(window, min_periods=window).max()
    df[f"high_{window}d"] = past_high
    df[f"breakout_{window}d"] = df[price_col] > past_high
    return df


# ---------------------------------------------------------------------------
# 成交量指标
# ---------------------------------------------------------------------------

def calc_volume_ratio(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    量比 = 当日成交额 / 过去 N 日平均成交额。
    新增列：vol_ratio_{window}d
    """
    df = df.copy()
    avg_amount = df["amount"].shift(1).rolling(window, min_periods=5).mean()
    df[f"vol_ratio_{window}d"] = df["amount"] / avg_amount
    return df


# ---------------------------------------------------------------------------
# 相对强度
# ---------------------------------------------------------------------------

def calc_relative_strength(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    window: int = 20,
) -> pd.DataFrame:
    """
    相对强度 = 股票近 N 日涨幅 - 同期指数涨幅。

    参数：
        df       : 单只股票 DataFrame，含 trade_date, close_qfq
        index_df : 指数 DataFrame，含 trade_date, close
        window   : 计算窗口

    新增列：rel_strength_{window}d（单位：百分比）
    """
    df = df.copy()
    price_col = "close_qfq" if "close_qfq" in df.columns else "close"

    stock_ret = df[price_col].pct_change(window)

    idx = index_df[["trade_date", "close"]].set_index("trade_date")["close"]
    idx_ret = idx.pct_change(window)
    idx_ret.index.name = "trade_date"

    df = df.set_index("trade_date")
    df[f"rel_strength_{window}d"] = (stock_ret.values - idx_ret.reindex(df.index).values) * 100
    return df.reset_index()


# ---------------------------------------------------------------------------
# 大盘过滤
# ---------------------------------------------------------------------------

def index_above_ma(index_df: pd.DataFrame, ma_window: int = 20) -> pd.Series:
    """
    返回一个以 trade_date 为索引的布尔 Series：
    当日指数收盘价是否在 N 日均线之上。
    """
    df = index_df.copy().sort_values("trade_date")
    df["index_ma"] = df["close"].rolling(ma_window, min_periods=ma_window).mean()
    df["above_ma"] = df["close"] > df["index_ma"]
    return df.set_index("trade_date")["above_ma"]


# ---------------------------------------------------------------------------
# 一次性计算所有指标（回测用）
# ---------------------------------------------------------------------------

def calc_all_indicators(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    ma_windows: tuple[int, ...] = (10, 20, 60),
    breakout_window: int = 20,
    vol_window: int = 20,
    rs_window: int = 20,
) -> pd.DataFrame:
    """
    对单只股票 DataFrame 计算全部指标，返回增强后的 DataFrame。
    """
    df = calc_ma(df, list(ma_windows))
    df = calc_ma_slope(df, f"ma{ma_windows[1]}")  # 默认对 ma20 计算斜率
    df = calc_breakout(df, breakout_window)
    df = calc_volume_ratio(df, vol_window)
    df = calc_relative_strength(df, index_df, rs_window)
    return df
