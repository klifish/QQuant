"""
每日信号报告生成脚本（盘后运行）。

用法：
  python scripts/daily_report.py              # 今日
  python scripts/daily_report.py --date 20231201
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.config import load_config
from src.data_cleaner import load_stock_qfq
from src.indicators import calc_all_indicators, index_above_ma
from src.universe_filter import get_universe
from src.signal_engine import generate_buy_signals, generate_sell_signals
from src.signal_ranker import rank_signals
from src.monitor import run_daily_checks
from src.portfolio_manager import Portfolio
from src.report_generator import generate_daily_report

import pandas as pd


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.today().strftime("%Y%m%d"))
    parser.add_argument("--cash", type=float, default=1_000_000,
                        help="初始模拟资金（仅用于报告展示）")
    args = parser.parse_args()
    date = args.date

    cfg = load_config()
    conn = sqlite3.connect(cfg["data"]["db_path"])

    logger.info(f"=== 生成 {date} 日报 ===")

    # 系统检查
    anomalies = run_daily_checks(conn, date=date)

    # 股票池
    universe = get_universe(
        date, conn,
        min_listed_days=cfg["universe"]["min_listed_days"],
        min_volume_20d=cfg["universe"]["min_volume_20d"],
    )

    # 指数数据
    index_df = pd.read_sql(
        "SELECT * FROM index_daily WHERE ts_code='399300.SZ' ORDER BY trade_date",
        conn
    )
    idx_above = index_above_ma(index_df, ma_window=cfg["strategy"]["index_ma"])
    idx_val = idx_above.get(date, False)

    # 加载候选股票数据并计算指标
    price_data = {}
    if not universe.empty:
        for code in universe["ts_code"].tolist():
            df = load_stock_qfq(conn, code)
            if not df.empty:
                try:
                    df = calc_all_indicators(df, index_df)
                    price_data[code] = df
                except Exception as e:
                    logger.debug(f"{code} 指标计算失败: {e}")

    # 买入信号
    candidates = generate_buy_signals(
        date,
        list(price_data.keys()),
        price_data,
        index_above_ma=bool(idx_val),
        ma_slow=cfg["strategy"]["ma_slow"],
        ma_fast=cfg["strategy"]["ma_fast"],
        breakout_window=cfg["strategy"]["breakout_window"],
    )
    ranked = rank_signals(candidates, top_n=cfg["backtest"]["top_n_signals"])

    # 模拟持仓（实盘模式需从数据库加载）
    portfolio = Portfolio(initial_cash=args.cash)

    # 价格快照（当日收盘价）
    price_map = {}
    for code in price_data:
        row = price_data[code][price_data[code]["trade_date"] == date]
        if not row.empty:
            price_map[code] = row.iloc[0].get("close_qfq", row.iloc[0].get("close"))

    # 生成报告
    out_path = Path("reports/daily") / f"{date}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = generate_daily_report(
        date=date,
        portfolio=portfolio,
        buy_candidates=ranked,
        sell_signals=[],
        price_map=price_map,
        strategy_state="normal",
        anomalies=anomalies if anomalies else None,
        output_path=str(out_path),
    )

    print(report)
    logger.info(f"日报已保存：{out_path}")
    conn.close()
