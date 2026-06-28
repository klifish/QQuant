"""
Edge 探针：向量化统计不同入场条件的"前瞻收益"，用数据选方向。

不是回测，不模拟持仓/风控/资金，只回答一个问题：
  在全样本上，满足某入场条件的那些「股票-日」，未来 N 日平均能赚/亏多少（扣费后）、胜率多少？

对比：突破(现策略) / 回调到MA20 / 上升趋势中超跌 / 纯短期超跌 / 无条件基准。
正确前复权（close×adj_factor/最新factor）现算，剔除 ST、当日涨停（买不进）、低流动性。

逐股循环累加统计量，内存友好（一次只持有一只股票）。

用法：
  python scripts/edge_probe.py
"""

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger

from src.config import load_config

ROUND_TRIP_COST = 0.0095   # 双向：佣金*2 + 印花 + 滑点*2 的近似
MIN_AMT20 = 5e7            # 近20日均额 > 5000万（与策略票池一致）


def _signal_masks(cq, ma20, ma60, ma20p, hi20, ret3, base, up, ro):
    """返回 {名称: 布尔mask}。所有入参为同长度 numpy 数组。"""
    near_ma20 = (cq <= ma20 * 1.03) & (cq >= ma20 * 0.95)
    return {
        "无条件基准(可交易全样本)": base,
        "突破20日新高[现策略]":      up & (cq > hi20),
        "突破+大盘risk_on":          up & (cq > hi20) & ro,
        "回调到MA20(上升趋势中)":     up & near_ma20,
        "回调到MA20+risk_on":        up & near_ma20 & ro,
        "上升趋势中超跌(3日<-6%)":    base & (cq > ma60) & (ret3 <= -0.06),
        "上升趋势超跌+risk_on":       base & (cq > ma60) & (ret3 <= -0.06) & ro,
        "纯短期超跌(3日<-8%)":        base & (ret3 <= -0.08),
    }


def main():
    cfg = load_config()
    conn = sqlite3.connect(cfg["data"]["db_path"])

    logger.info("加载行情（分块+降精度，控内存）...")
    parts = []
    for ch in pd.read_sql(
        "SELECT ts_code,trade_date,close,amount,adj_factor,is_st,is_limit_up "
        "FROM stock_daily ORDER BY ts_code,trade_date", conn, chunksize=500_000):
        ch["close"] = ch["close"].astype("float32")
        ch["amount"] = ch["amount"].astype("float32")
        ch["adj_factor"] = ch["adj_factor"].fillna(1.0).astype("float32")
        ch["is_st"] = ch["is_st"].fillna(0).astype("int8")
        ch["is_limit_up"] = ch["is_limit_up"].fillna(0).astype("int8")
        ch["trade_date"] = ch["trade_date"].astype("int32")
        parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    del parts

    # 大盘 regime（沪深300 在 MA60 上方）
    idx = pd.read_sql(
        "SELECT trade_date,close FROM index_daily WHERE ts_code='399300.SZ' "
        "ORDER BY trade_date", conn)
    idx["trade_date"] = idx["trade_date"].astype("int32")
    idx["risk_on"] = idx["close"] > idx["close"].rolling(60).mean()
    risk_map = dict(zip(idx["trade_date"].to_numpy(), idx["risk_on"].to_numpy()))
    conn.close()

    logger.info("逐股计算指标与前瞻收益，累加统计...")
    # 每个信号累加：n5, sum5, win5, n10, sum10, win10
    acc = defaultdict(lambda: [0, 0.0, 0, 0, 0.0, 0])

    for code, sub in df.groupby("ts_code", sort=False, observed=True):
        if len(sub) < 80:
            continue
        s = sub["close"].astype("float64") * sub["adj_factor"].astype("float64")
        s = s / float(sub["adj_factor"].iloc[-1])    # 正确前复权
        cq = s.to_numpy()
        ma20 = s.rolling(20).mean().to_numpy()
        ma60 = s.rolling(60).mean().to_numpy()
        ma20p = np.concatenate([[np.nan], ma20[:-1]])
        hi20 = s.shift(1).rolling(20).max().to_numpy()
        ret3 = s.pct_change(3).to_numpy()
        amt20 = sub["amount"].rolling(20).mean().to_numpy() * 1000.0
        n = len(cq)
        fwd5 = np.full(n, np.nan); fwd5[:-5] = cq[5:] / cq[:-5] - 1
        fwd10 = np.full(n, np.nan); fwd10[:-10] = cq[10:] / cq[:-10] - 1
        isst = sub["is_st"].to_numpy()
        islu = sub["is_limit_up"].to_numpy()
        ro = np.array([bool(risk_map.get(int(d), False)) for d in sub["trade_date"].to_numpy()])

        with np.errstate(invalid="ignore"):
            base = (isst == 0) & (islu == 0) & (amt20 > MIN_AMT20) & ~np.isnan(ma60)
            up = base & (cq > ma60) & (ma20 > ma20p)
            masks = _signal_masks(cq, ma20, ma60, ma20p, hi20, ret3, base, up, ro)

        v5 = ~np.isnan(fwd5)
        v10 = ~np.isnan(fwd10)
        for name, m in masks.items():
            m = np.asarray(m, dtype=bool)
            m5 = m & v5
            if m5.any():
                a = acc[name]
                a[0] += int(m5.sum()); a[1] += float(fwd5[m5].sum()); a[2] += int((fwd5[m5] > 0).sum())
                m10 = m & v10
                a[3] += int(m10.sum()); a[4] += float(fwd10[m10].sum()); a[5] += int((fwd10[m10] > 0).sum())

    rows = []
    for name, (n5, s5, w5, n10, s10, w10) in acc.items():
        if n5 == 0:
            continue
        rows.append({
            "入场条件": name, "样本数": n5,
            "fwd5毛": s5 / n5, "fwd5净": s5 / n5 - ROUND_TRIP_COST, "fwd5胜率": w5 / n5,
            "fwd10毛": s10 / n10 if n10 else 0,
            "fwd10净": (s10 / n10 - ROUND_TRIP_COST) if n10 else 0,
            "fwd10胜率": w10 / n10 if n10 else 0,
        })

    res = pd.DataFrame(rows)
    pd.set_option("display.unicode.east_asian_width", True)
    logger.info(f"双向成本假设 {ROUND_TRIP_COST:.2%}；'净'=前瞻收益−成本。看 fwd5净/fwd10净是否>0。\n")
    for c in ["fwd5毛", "fwd5净", "fwd5胜率", "fwd10毛", "fwd10净", "fwd10胜率"]:
        res[c] = res[c].map(lambda x: f"{x:+.2%}")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
