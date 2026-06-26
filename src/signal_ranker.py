"""
信号排序模块：对买入候选按综合评分排序，输出 Top N。

评分权重（可在 config.yaml 中扩展）：
  相对强度（超额收益）: 50%
  量比              : 30%
  均线斜率强度      : 20%
"""

import pandas as pd
import numpy as np


def rank_signals(
    candidates: pd.DataFrame,
    top_n: int = 15,
    rs_window: int = 20,
    vol_window: int = 20,
    weights: dict | None = None,
) -> pd.DataFrame:
    """
    对买入候选 DataFrame 进行综合评分排序。

    参数：
        candidates : generate_buy_signals() 的返回值
        top_n      : 最多返回的候选数量
        rs_window  : 相对强度窗口（用于列名匹配）
        vol_window : 量比窗口（用于列名匹配）
        weights    : 各指标权重，默认 {'rs': 0.5, 'vol': 0.3, 'ma': 0.2}

    返回：
        按 score 降序排列的 Top N DataFrame，新增 score, rank 列
    """
    if candidates.empty:
        return candidates

    if weights is None:
        weights = {"rs": 0.5, "vol": 0.3, "ma": 0.2}

    df = candidates.copy()

    rs_col = f"rel_strength_{rs_window}d"
    vol_col = f"vol_ratio_{vol_window}d"

    # 归一化到 [0, 1]，缺失值用中位数填充
    def minmax_norm(s: pd.Series) -> pd.Series:
        s = s.fillna(s.median())
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series(0.5, index=s.index)
        return (s - mn) / (mx - mn)

    score = pd.Series(0.0, index=df.index)

    if rs_col in df.columns:
        score += weights["rs"] * minmax_norm(df[rs_col])

    if vol_col in df.columns:
        score += weights["vol"] * minmax_norm(df[vol_col])

    # 均线斜率强度：用 (close - ma20) / ma20 代表距离快线的强度
    if "close_qfq" in df.columns and "ma20" in df.columns:
        ma_dist = (df["close_qfq"] - df["ma20"]) / df["ma20"]
        score += weights["ma"] * minmax_norm(ma_dist)

    df["score"] = score.round(4)
    df = df.sort_values("score", ascending=False).head(top_n)
    df["rank"] = range(1, len(df) + 1)

    return df.reset_index(drop=True)
