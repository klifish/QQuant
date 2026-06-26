"""
数据质量验证脚本：下载后运行，确认数据可用于回测。

用法：
  python scripts/validate_data.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger
from src.config import load_config


def validate(cfg: dict) -> bool:
    conn = sqlite3.connect(cfg["data"]["db_path"])
    ok = True

    logger.info("=== 数据质量验证 ===")

    # 1. 基础表行数
    tables = ["stock_basic", "stock_daily", "index_daily", "trade_cal"]
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        status = "✅" if count > 0 else "❌"
        logger.info(f"{status} {table}: {count:,} 行")
        if count == 0:
            ok = False

    # 2. 日线数据时间范围
    row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT ts_code) FROM stock_daily"
    ).fetchone()
    if row[0]:
        logger.info(f"✅ stock_daily 范围：{row[0]} ~ {row[1]}，{row[2]:,} 只股票")
        if int(row[0][:4]) > 2015:
            logger.warning(f"⚠️ 数据起点 {row[0]} 晚于 2015年，历史回测覆盖不足")
    else:
        logger.error("❌ stock_daily 无数据")
        ok = False

    # 3. ST 标记检查
    st_count = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE is_st = 1").fetchone()[0]
    logger.info(f"{'✅' if st_count > 0 else '⚠️'} ST 标记：{st_count:,} 行（0行表示未运行清洗）")

    # 4. 停牌标记检查（vol=0 推算）
    sus_count = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE is_suspend = 1").fetchone()[0]
    logger.info(f"{'✅' if sus_count >= 0 else '⚠️'} 停牌标记（vol=0 推算）：{sus_count:,} 行")

    # 5. 价格异常检测（涨跌幅超25%且非涨跌停）
    anom = conn.execute("""
        SELECT COUNT(*) FROM stock_daily
        WHERE ABS(pct_chg) > 25
          AND is_limit_up = 0 AND is_limit_dn = 0
    """).fetchone()[0]
    if anom > 0:
        logger.warning(f"⚠️ 疑似价格异常：{anom} 行（涨跌幅>25%但非涨跌停）")
    else:
        logger.info("✅ 无明显价格异常")

    # 6. 缺失复权因子
    no_adj = conn.execute(
        "SELECT COUNT(*) FROM stock_daily WHERE adj_factor IS NULL OR adj_factor = 0"
    ).fetchone()[0]
    if no_adj > 0:
        logger.warning(f"⚠️ 缺失复权因子：{no_adj:,} 行")
    else:
        logger.info("✅ 复权因子完整")

    # 7. 指数数据检查
    idx_count = conn.execute(
        "SELECT COUNT(*) FROM index_daily WHERE ts_code='399300.SZ'"
    ).fetchone()[0]
    status = "✅" if idx_count > 500 else "❌"
    logger.info(f"{status} 沪深300日线：{idx_count} 行")
    if idx_count < 500:
        ok = False

    conn.close()
    logger.info(f"\n=== 验证结果：{'通过 ✅' if ok else '存在问题 ❌，请检查上述警告'} ===")
    return ok


if __name__ == "__main__":
    cfg = load_config()
    passed = validate(cfg)
    sys.exit(0 if passed else 1)
