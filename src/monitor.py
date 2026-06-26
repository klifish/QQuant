"""
系统监控模块：检查数据异常、仓位越界、程序错误。
"""

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger


def check_data_freshness(
    conn: sqlite3.Connection,
    max_lag_days: int = 3,
) -> list[str]:
    """
    检查 stock_daily 最新数据日期是否过旧（超过 N 个工作日未更新）。
    """
    issues = []
    row = conn.execute(
        "SELECT MAX(trade_date) FROM stock_daily"
    ).fetchone()
    if not row or not row[0]:
        issues.append("stock_daily 表无数据")
        return issues

    latest = datetime.strptime(row[0], "%Y%m%d")
    today = datetime.today()
    lag = (today - latest).days

    if lag > max_lag_days:
        issues.append(f"数据滞后 {lag} 天（最新：{row[0]}，今日：{today.strftime('%Y%m%d')}）")

    return issues


def check_price_anomalies(
    conn: sqlite3.Connection,
    date: str,
    pct_threshold: float = 25.0,
) -> list[str]:
    """
    检查指定日期的价格异常：单日涨跌幅超过阈值但未标记为涨跌停的股票。
    """
    df = pd.read_sql(
        """
        SELECT ts_code, pct_chg
        FROM stock_daily
        WHERE trade_date = ?
          AND is_limit_up = 0
          AND is_limit_dn = 0
          AND ABS(pct_chg) > ?
        """,
        conn,
        params=[date, pct_threshold],
    )
    issues = []
    for _, row in df.iterrows():
        issues.append(
            f"价格异常 {row['ts_code']}：涨跌幅 {row['pct_chg']:.1f}%（非涨跌停）"
        )
    return issues


def check_missing_dates(
    conn: sqlite3.Connection,
    ts_code: str,
    start: str,
    end: str,
) -> list[str]:
    """
    对比交易日历，找出单只股票缺失的交易日（已停牌日除外）。
    """
    trade_cal = pd.read_sql(
        "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
        "AND cal_date>=? AND cal_date<=?",
        conn, params=[start, end]
    )["cal_date"].tolist()

    existing = pd.read_sql(
        "SELECT trade_date FROM stock_daily WHERE ts_code=? AND trade_date>=? AND trade_date<=?",
        conn, params=[ts_code, start, end]
    )["trade_date"].tolist()

    suspended = pd.read_sql(
        "SELECT suspend_date FROM suspend_d WHERE ts_code=? AND suspend_date>=? AND suspend_date<=?",
        conn, params=[ts_code, start, end]
    )["suspend_date"].tolist()

    missing = [
        d for d in trade_cal
        if d not in existing and d not in suspended
    ]
    return [f"{ts_code} 缺失交易日：{d}" for d in missing[:10]]  # 最多报告10条


def check_portfolio_health(portfolio, cfg) -> list[str]:
    """
    检查持仓是否违反风险规则。
    """
    issues = []
    total_equity = portfolio.cash + sum(
        pos.cost for pos in portfolio.positions.values()
    )

    # 总仓位
    total_exposure = 1 - (portfolio.cash / total_equity) if total_equity > 0 else 0
    if total_exposure > cfg.max_total_exposure + 0.02:
        issues.append(f"总仓位 {total_exposure:.1%} 超过上限 {cfg.max_total_exposure:.0%}")

    # 单票超限
    for code, pos in portfolio.positions.items():
        pct = pos.cost / total_equity
        if pct > cfg.max_position_pct + 0.02:
            issues.append(f"{code} 仓位 {pct:.1%} 超过单票上限 {cfg.max_position_pct:.0%}")

    return issues


def run_daily_checks(
    conn: sqlite3.Connection,
    portfolio=None,
    risk_cfg=None,
    date: str | None = None,
) -> list[str]:
    """
    汇总所有日常检查，返回所有异常信息列表。
    """
    if date is None:
        date = datetime.today().strftime("%Y%m%d")

    all_issues = []

    issues = check_data_freshness(conn)
    if issues:
        all_issues.extend(issues)
        logger.warning(f"数据新鲜度问题：{issues}")

    issues = check_price_anomalies(conn, date)
    if issues:
        all_issues.extend(issues)
        logger.warning(f"价格异常：{len(issues)} 条")

    if portfolio and risk_cfg:
        issues = check_portfolio_health(portfolio, risk_cfg)
        if issues:
            all_issues.extend(issues)
            logger.warning(f"持仓健康问题：{issues}")

    if not all_issues:
        logger.info(f"{date} 系统检查通过，无异常")

    return all_issues
