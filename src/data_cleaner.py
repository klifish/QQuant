"""
数据清洗模块：对已入库的原始数据做标记和前复权处理。

职责：
  1. 前复权（qfq）：用 adj_factor 将所有 OHLC 调整为前复权价
  2. 标记 ST 股票（is_st）
  3. 标记停牌日（is_suspend）
  4. 标记一字涨跌停（is_limit_up / is_limit_dn）
  5. 输出清洗质量报告
"""

import sqlite3

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# 前复权
# ---------------------------------------------------------------------------

def apply_qfq(df: pd.DataFrame) -> pd.DataFrame:
    """
    对单只股票的日线 DataFrame 做前复权。

    前复权逻辑：
      adj_close = close × (最新复权因子 / 当日复权因子)
    以最新一天的复权因子为基准（= 1.0），历史价格向前调整。

    参数 df 需含列：open, high, low, close, pre_close, adj_factor
    返回新增 open_qfq, high_qfq, low_qfq, close_qfq 列的 DataFrame。
    """
    df = df.copy()
    if "adj_factor" not in df.columns or df["adj_factor"].isna().all():
        for col in ("open_qfq", "high_qfq", "low_qfq", "close_qfq"):
            df[col] = df[col.replace("_qfq", "")]
        return df

    # 最新复权因子（按 trade_date 排序后取最后一行）
    df = df.sort_values("trade_date")
    latest_factor = df["adj_factor"].iloc[-1]
    ratio = latest_factor / df["adj_factor"]

    for raw_col in ("open", "high", "low", "close"):
        df[f"{raw_col}_qfq"] = (df[raw_col] * ratio).round(4)

    return df


# ---------------------------------------------------------------------------
# ST 标记
# ---------------------------------------------------------------------------

def mark_st(conn: sqlite3.Connection) -> int:
    """
    根据 stock_basic 中的 name 字段，将含 'ST' 的股票的 is_st 标记为 1。
    返回更新行数。
    """
    st_codes = pd.read_sql(
        "SELECT ts_code FROM stock_basic WHERE name LIKE '%ST%'",
        conn,
    )["ts_code"].tolist()

    if not st_codes:
        return 0

    placeholders = ",".join("?" * len(st_codes))
    cursor = conn.execute(
        f"UPDATE stock_daily SET is_st = 1 WHERE ts_code IN ({placeholders})",
        st_codes,
    )
    conn.commit()
    logger.info(f"ST 标记：{cursor.rowcount} 行")
    return cursor.rowcount


# ---------------------------------------------------------------------------
# 停牌标记
# ---------------------------------------------------------------------------

def mark_suspend(conn: sqlite3.Connection) -> int:
    """
    用成交量推算停牌：vol = 0 视为停牌（无需 suspend_d 接口，仅需 120 积分）。

    注：Tushare daily 接口对全天停牌通常不返回数据行，所以缺失日期即停牌。
    此函数本想捕捉"有价格记录但成交量为零"的部分停牌场景，但实测 Tushare
    日线里 vol=0 / vol IS NULL 的行数为 0——停牌一律表现为整行缺失，从不出现
    vol=0 的行。因此本函数恒命中 0 行、is_suspend 列实际恒为 0，仅作占位。
    停牌在回测中由"当日无 K 线"分支处理（见 backtester._last_close_on_or_before
    及买卖执行的缺行跳过逻辑），不依赖此列。
    """
    cursor = conn.execute(
        "UPDATE stock_daily SET is_suspend = 1 WHERE vol = 0 OR vol IS NULL"
    )
    conn.commit()
    logger.info(f"停牌标记（vol=0 推算）：{cursor.rowcount} 行")
    return cursor.rowcount


# ---------------------------------------------------------------------------
# 一字涨跌停标记
# ---------------------------------------------------------------------------

def mark_limit(conn: sqlite3.Connection) -> int:
    """
    用 pct_chg 推算涨跌停，无需 stk_limit 接口（仅需 120 积分）。

    涨停阈值规则：
      科创板 (688xxx.SH)            : ±20%
      创业板 (3xxx.SZ, 2020-08-24+) : ±20%
      ST 股票                        : ±5%
      其余主板                       : ±10%

    注：阈值取 -0.5% 容差（如 9.5% 而非 10%）以容纳浮点误差，
    且我们的股票池已过滤掉上市不足365天的新股（首日无涨跌停限制）。
    """
    conn.execute("""
        UPDATE stock_daily SET is_limit_up = 1
        WHERE
            (ts_code LIKE '688%' AND pct_chg >= 19.5)
            OR (ts_code LIKE '3%' AND trade_date >= '20200824' AND pct_chg >= 19.5)
            OR (is_st = 1 AND pct_chg >= 4.9)
            OR (ts_code NOT LIKE '688%'
                AND NOT (ts_code LIKE '3%' AND trade_date >= '20200824')
                AND is_st = 0
                AND pct_chg >= 9.5)
    """)
    up_rows = conn.execute("SELECT changes()").fetchone()[0]

    conn.execute("""
        UPDATE stock_daily SET is_limit_dn = 1
        WHERE
            (ts_code LIKE '688%' AND pct_chg <= -19.5)
            OR (ts_code LIKE '3%' AND trade_date >= '20200824' AND pct_chg <= -19.5)
            OR (is_st = 1 AND pct_chg <= -4.9)
            OR (ts_code NOT LIKE '688%'
                AND NOT (ts_code LIKE '3%' AND trade_date >= '20200824')
                AND is_st = 0
                AND pct_chg <= -9.5)
    """)
    dn_rows = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    logger.info(f"涨停标记（pct_chg 推算）：{up_rows} 行；跌停标记：{dn_rows} 行")
    return up_rows + dn_rows


# ---------------------------------------------------------------------------
# 完整清洗流程
# ---------------------------------------------------------------------------

def run_clean_pipeline(conn: sqlite3.Connection) -> None:
    """对已入库数据执行完整清洗流程（仅标记，不修改原始价格列）。"""
    logger.info("=== 开始数据清洗 ===")
    mark_st(conn)
    mark_suspend(conn)
    mark_limit(conn)
    logger.info("=== 数据清洗完成 ===")


# ---------------------------------------------------------------------------
# 按需读取清洗后的数据（含前复权价格）
# ---------------------------------------------------------------------------

def load_stock_qfq(
    conn: sqlite3.Connection,
    ts_code: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """
    读取单只股票的日线数据并做前复权，返回含 *_qfq 列的 DataFrame。
    """
    where = "WHERE ts_code = ?"
    params: list = [ts_code]
    if start:
        where += " AND trade_date >= ?"
        params.append(start)
    if end:
        where += " AND trade_date <= ?"
        params.append(end)

    df = pd.read_sql(
        f"SELECT * FROM stock_daily {where} ORDER BY trade_date",
        conn,
        params=params,
    )
    if df.empty:
        return df

    return apply_qfq(df)


def load_all_qfq(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    exclude_st: bool = True,
    exclude_suspend: bool = True,
) -> pd.DataFrame:
    """
    读取全市场日线数据并做前复权。数据量较大，建议配合 universe_filter 过滤。
    """
    conditions = []
    params: list = []

    if start:
        conditions.append("trade_date >= ?")
        params.append(start)
    if end:
        conditions.append("trade_date <= ?")
        params.append(end)
    if exclude_st:
        conditions.append("is_st = 0")
    if exclude_suspend:
        conditions.append("is_suspend = 0")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    df = pd.read_sql(
        f"SELECT * FROM stock_daily {where} ORDER BY ts_code, trade_date",
        conn,
        params=params,
    )
    if df.empty:
        return df

    # 按股票分组做前复权
    groups = []
    for code, g in df.groupby("ts_code"):
        groups.append(apply_qfq(g))
    return pd.concat(groups, ignore_index=True)
