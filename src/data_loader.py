"""
数据下载模块：从 Tushare 获取 A 股数据，存入 SQLite。

所需 Tushare 积分：120（仅用基础行情接口）。
停牌/涨跌停通过 vol=0 和 pct_chg 推算，无需 suspend_d / stk_limit 接口。

建表结构：
  stock_basic   — 股票基础信息（含退市股）
  stock_daily   — 日线行情
  index_daily   — 指数日线
  trade_cal     — 交易日历
"""

import time
import sqlite3
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import tushare as ts
from loguru import logger
from tqdm import tqdm

from src.config import load_config, get_tushare_token


# ---------------------------------------------------------------------------
# 数据库初始化
# ---------------------------------------------------------------------------

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code      TEXT NOT NULL,
    symbol       TEXT,
    name         TEXT,
    area         TEXT,
    industry     TEXT,
    list_date    TEXT,
    delist_date  TEXT,
    list_status  TEXT,
    PRIMARY KEY (ts_code)
);

CREATE TABLE IF NOT EXISTS stock_daily (
    ts_code      TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    pre_close    REAL,
    change       REAL,
    pct_chg      REAL,
    vol          REAL,
    amount       REAL,
    adj_factor   REAL,
    is_st        INTEGER DEFAULT 0,
    is_suspend   INTEGER DEFAULT 0,
    is_limit_up  INTEGER DEFAULT 0,
    is_limit_dn  INTEGER DEFAULT 0,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS trade_cal (
    exchange   TEXT NOT NULL,
    cal_date   TEXT NOT NULL,
    is_open    INTEGER,
    PRIMARY KEY (exchange, cal_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily (trade_date);
CREATE INDEX IF NOT EXISTS idx_index_daily_date ON index_daily (trade_date);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_CREATE_TABLES)
    conn.commit()
    logger.info(f"数据库初始化完成：{db_path}")
    return conn


# ---------------------------------------------------------------------------
# Tushare 客户端
# ---------------------------------------------------------------------------

def get_pro(cfg: dict) -> ts.pro_api:
    token = get_tushare_token(cfg)
    ts.set_token(token)
    return ts.pro_api()


# ---------------------------------------------------------------------------
# 基础信息
# ---------------------------------------------------------------------------

def download_stock_basic(pro: ts.pro_api, conn: sqlite3.Connection) -> pd.DataFrame:
    """下载全量股票基础信息，包含已退市股票（list_status=D）。"""
    frames = []
    for status in ["L", "D", "P"]:  # L上市、D退市、P暂停上市
        df = pro.stock_basic(
            exchange="",
            list_status=status,
            fields="ts_code,symbol,name,area,industry,list_date,delist_date,list_status",
        )
        frames.append(df)
        time.sleep(0.3)

    result = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")
    result.to_sql("stock_basic", conn, if_exists="replace", index=False)
    conn.commit()
    logger.info(f"股票基础信息：{len(result)} 条")
    return result


def download_trade_cal(pro: ts.pro_api, conn: sqlite3.Connection,
                       start: str = "20150101") -> pd.DataFrame:
    today = datetime.today().strftime("%Y%m%d")
    df = pro.trade_cal(exchange="SSE", start_date=start, end_date=today)
    df.to_sql("trade_cal", conn, if_exists="replace", index=False)
    conn.commit()
    logger.info(f"交易日历：{len(df)} 条")
    return df


# ---------------------------------------------------------------------------
# 日线数据
# ---------------------------------------------------------------------------

def _get_existing_dates(conn: sqlite3.Connection, ts_code: str) -> set[str]:
    rows = conn.execute(
        "SELECT trade_date FROM stock_daily WHERE ts_code = ?", (ts_code,)
    ).fetchall()
    return {r[0] for r in rows}


def download_daily_one(
    pro: ts.pro_api,
    ts_code: str,
    start: str,
    end: str,
    conn: sqlite3.Connection,
    sleep: float = 0.35,
    adj: str = "qfq",
) -> int:
    """下载单只股票日线，跳过已存在日期（断点续传）。返回新增行数。"""
    existing = _get_existing_dates(conn, ts_code)

    try:
        df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
        time.sleep(sleep)
        if df is None or df.empty:
            return 0

        # 获取复权因子
        adj_df = pro.adj_factor(ts_code=ts_code, start_date=start, end_date=end)
        time.sleep(sleep)

        if adj_df is not None and not adj_df.empty:
            df = df.merge(adj_df[["trade_date", "adj_factor"]], on="trade_date", how="left")
        else:
            df["adj_factor"] = 1.0

        # 只保留新数据
        df = df[~df["trade_date"].isin(existing)].copy()
        if df.empty:
            return 0

        df["is_st"] = 0
        df["is_suspend"] = 0
        df["is_limit_up"] = 0
        df["is_limit_dn"] = 0

        cols = [
            "ts_code", "trade_date", "open", "high", "low", "close",
            "pre_close", "change", "pct_chg", "vol", "amount",
            "adj_factor", "is_st", "is_suspend", "is_limit_up", "is_limit_dn",
        ]
        df = df[[c for c in cols if c in df.columns]]
        df.to_sql("stock_daily", conn, if_exists="append", index=False)
        return len(df)

    except Exception as e:
        logger.warning(f"{ts_code} 下载失败: {e}")
        return 0


def download_all_daily(
    pro: ts.pro_api,
    conn: sqlite3.Connection,
    stock_basic: pd.DataFrame,
    start: str,
    end: str,
    sleep: float = 0.35,
) -> None:
    """批量下载全量股票日线，支持断点续传。"""
    codes = stock_basic["ts_code"].tolist()
    total_new = 0

    for code in tqdm(codes, desc="下载日线数据"):
        new_rows = download_daily_one(pro, code, start, end, conn, sleep)
        total_new += new_rows

    conn.commit()
    logger.info(f"日线下载完成，新增 {total_new} 条记录")


# ---------------------------------------------------------------------------
# 指数日线
# ---------------------------------------------------------------------------

def download_index_daily(
    pro: ts.pro_api,
    conn: sqlite3.Connection,
    index_codes: list[str] | None = None,
    start: str = "20150101",
) -> None:
    if index_codes is None:
        index_codes = ["399300.SZ", "000001.SH", "000905.SH"]  # 沪深300、上证、中证500

    today = datetime.today().strftime("%Y%m%d")
    for code in index_codes:
        df = pro.index_daily(ts_code=code, start_date=start, end_date=today)
        time.sleep(0.35)
        if df is not None and not df.empty:
            df.to_sql("index_daily", conn, if_exists="append", index=False)
            logger.info(f"指数 {code}：{len(df)} 条")

    conn.commit()


# ---------------------------------------------------------------------------
# 便捷入口：首次全量初始化
# ---------------------------------------------------------------------------

def full_init(cfg: dict | None = None) -> None:
    """首次运行：建库、下载所有基础数据。耗时较长（数小时）。"""
    if cfg is None:
        cfg = load_config()

    conn = init_db(cfg["data"]["db_path"])
    pro = get_pro(cfg)

    logger.info("=== 开始全量数据初始化 ===")
    basic = download_stock_basic(pro, conn)
    download_trade_cal(pro, conn, cfg["data"]["start_date"])
    download_index_daily(pro, conn, start=cfg["data"]["start_date"])
    download_all_daily(pro, conn, basic, cfg["data"]["start_date"],
                       cfg["data"]["end_date"] or datetime.today().strftime("%Y%m%d"))
    logger.info("=== 全量初始化完成 ===")
    conn.close()
