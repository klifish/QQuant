"""
股票池过滤模块：每日生成"可交易股票池"。

过滤条件：
  1. 非 ST / *ST
  2. 上市超过 N 天（默认 365）
  3. 近 20 日平均成交额 > 阈值（默认 5000 万元）
  4. 当日未停牌
  5. 当日非一字涨跌停
"""

import sqlite3

import pandas as pd
from loguru import logger


def get_universe(
    date: str,
    conn: sqlite3.Connection,
    min_listed_days: int = 365,
    min_volume_20d: float = 50_000_000,
) -> pd.DataFrame:
    """
    返回指定交易日的可交易股票池。

    参数：
        date           : 交易日，格式 YYYYMMDD
        conn           : SQLite 连接
        min_listed_days: 上市最少天数
        min_volume_20d : 近20日平均成交额最低值（元）

    返回：
        DataFrame，列包含 ts_code, name, industry, list_date
    """
    # 1. 当日有行情且未停牌、未一字涨跌停、非 ST
    daily_cond = pd.read_sql(
        """
        SELECT ts_code
        FROM stock_daily
        WHERE trade_date = ?
          AND is_st = 0
          AND is_suspend = 0
          AND is_limit_up = 0
          AND is_limit_dn = 0
        """,
        conn,
        params=[date],
    )
    if daily_cond.empty:
        logger.warning(f"{date} 无可用股票（可能非交易日或数据未下载）")
        return pd.DataFrame()

    candidate_codes = daily_cond["ts_code"].tolist()

    # 2. 上市时间超过 min_listed_days
    basic = pd.read_sql(
        "SELECT ts_code, name, industry, list_date FROM stock_basic "
        "WHERE list_status = 'L'",
        conn,
    )
    basic = basic[basic["ts_code"].isin(candidate_codes)].copy()
    basic["list_date"] = pd.to_datetime(basic["list_date"], format="%Y%m%d")
    query_date = pd.to_datetime(date, format="%Y%m%d")
    basic = basic[(query_date - basic["list_date"]).dt.days >= min_listed_days]

    if basic.empty:
        return pd.DataFrame()

    # 3. 近 20 日平均成交额
    codes_str = ",".join(f"'{c}'" for c in basic["ts_code"].tolist())
    vol20 = pd.read_sql(
        f"""
        SELECT ts_code, AVG(amount) AS avg_amount_20d
        FROM (
            SELECT ts_code, amount
            FROM stock_daily
            WHERE ts_code IN ({codes_str})
              AND trade_date <= ?
              AND is_suspend = 0
            ORDER BY trade_date DESC
            LIMIT {len(basic["ts_code"].tolist()) * 20}
        )
        GROUP BY ts_code
        HAVING COUNT(*) >= 10
        """,
        conn,
        params=[date],
    )
    # amount 单位为千元，换算为元
    vol20["avg_amount_20d"] = vol20["avg_amount_20d"] * 1000
    vol20 = vol20[vol20["avg_amount_20d"] >= min_volume_20d]

    universe = basic[basic["ts_code"].isin(vol20["ts_code"])].copy()
    universe = universe.merge(vol20, on="ts_code", how="left")

    logger.info(f"{date} 股票池：{len(universe)} 只")
    return universe.reset_index(drop=True)


def get_universe_batch(
    dates: list[str],
    conn: sqlite3.Connection,
    min_listed_days: int = 365,
    min_volume_20d: float = 50_000_000,
) -> dict[str, pd.DataFrame]:
    """批量生成多个交易日的股票池，用于回测。"""
    return {
        d: get_universe(d, conn, min_listed_days, min_volume_20d)
        for d in dates
    }
