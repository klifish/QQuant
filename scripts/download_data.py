"""
数据下载入口：首次运行执行全量初始化，后续运行做增量更新。

用法：
  export TUSHARE_TOKEN=your_token
  python scripts/download_data.py              # 全量（首次）
  python scripts/download_data.py --incremental  # 增量更新
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.config import load_config
from src.data_loader import (
    init_db, get_pro, download_stock_basic, download_trade_cal,
    download_index_daily, download_all_daily, full_init,
)
from src.data_cleaner import run_clean_pipeline


def incremental_update(cfg: dict) -> None:
    """增量更新：只下载最新数据。"""
    conn = sqlite3.connect(cfg["data"]["db_path"])
    pro = get_pro(cfg)
    today = datetime.today().strftime("%Y%m%d")

    # 找到 stock_daily 最新日期
    row = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()
    last_date = row[0] if row and row[0] else cfg["data"]["start_date"]
    logger.info(f"增量更新：{last_date} → {today}")

    basic = download_stock_basic(pro, conn)
    download_trade_cal(pro, conn, start=last_date)
    download_index_daily(pro, conn, start=last_date)
    download_all_daily(pro, conn, basic, start=last_date, end=today)
    run_clean_pipeline(conn)
    conn.close()
    logger.info("增量更新完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QQuant 数据下载工具")
    parser.add_argument("--incremental", action="store_true", help="增量更新模式")
    args = parser.parse_args()

    cfg = load_config()

    if args.incremental:
        incremental_update(cfg)
    else:
        full_init(cfg)
        # 全量下载后执行清洗
        conn = sqlite3.connect(cfg["data"]["db_path"])
        run_clean_pipeline(conn)
        conn.close()
