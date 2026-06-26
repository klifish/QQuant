"""
回测模块：基于 vectorbt 的多股票日线回测。

使用流程：
  1. validate_framework() — 用双均线验证框架本身正确性
  2. run_backtest()       — 运行完整趋势突破策略回测
  3. calc_metrics()       — 计算绩效指标
  4. segment_report()     — 按年份/市场阶段分段输出

关键约定：
  - 信号基于 T 日收盘，T+1 开盘成交（open 列）
  - 涨跌停日不强制成交（跳过）
  - 含已退市股票，防止幸存者偏差
"""

import sqlite3
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    HAS_VBT = False
    logger.warning("vectorbt 未安装，回测功能不可用。运行 pip install vectorbt")

from src.data_cleaner import apply_qfq
from src.indicators import calc_all_indicators, index_above_ma
from src.signal_engine import generate_buy_signals, generate_sell_signals
from src.signal_ranker import rank_signals


# ---------------------------------------------------------------------------
# 框架验证：双均线策略（用于确认 vectorbt 配置正确）
# ---------------------------------------------------------------------------

def validate_framework(
    conn: sqlite3.Connection,
    ts_code: str = "600519.SH",  # 贵州茅台，数据较完整
    start: str = "20180101",
    end: str = "20231231",
    fast: int = 20,
    slow: int = 60,
) -> Optional[pd.DataFrame]:
    """
    用双均线金叉/死叉策略验证 vectorbt 框架。
    预期：能正常运行并输出年化收益、最大回撤等统计。
    """
    if not HAS_VBT:
        logger.error("请先安装 vectorbt")
        return None

    df = pd.read_sql(
        "SELECT * FROM stock_daily WHERE ts_code=? AND trade_date>=? AND trade_date<=? "
        "ORDER BY trade_date",
        conn, params=[ts_code, start, end]
    )
    if df.empty:
        logger.error(f"无数据：{ts_code} {start}-{end}")
        return None

    df = apply_qfq(df)
    price_col = "close_qfq"
    close = df.set_index("trade_date")[price_col]
    open_ = df.set_index("trade_date")["open_qfq"]

    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()

    # 金叉买入，死叉卖出（T日信号，T+1开盘成交）
    entries = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))
    exits   = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))

    pf = vbt.Portfolio.from_signals(
        open_.shift(-1),   # T+1 开盘价成交
        entries=entries,
        exits=exits,
        fees=0.00025 * 2 + 0.001,  # 买卖佣金 + 印花税
        slippage=0.002,
        init_cash=100_000,
        freq="D",
    )

    stats = pf.stats()
    logger.info(f"\n=== 框架验证：{ts_code} 双均线 MA{fast}/MA{slow} ===\n{stats}")
    return stats


# ---------------------------------------------------------------------------
# 完整策略回测（事件驱动，逐日模拟）
# ---------------------------------------------------------------------------

def _load_all_price_data(
    conn: sqlite3.Connection,
    start: str,
    end: str,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """加载全量股票日线和指数日线，做前复权。"""
    stock_df = pd.read_sql(
        "SELECT * FROM stock_daily WHERE trade_date>=? AND trade_date<=? ORDER BY ts_code, trade_date",
        conn, params=[start, end]
    )
    index_df = pd.read_sql(
        "SELECT * FROM index_daily WHERE ts_code='399300.SZ' AND trade_date>=? AND trade_date<=? "
        "ORDER BY trade_date",
        conn, params=[start, end]
    )

    price_data: dict[str, pd.DataFrame] = {}
    for code, g in stock_df.groupby("ts_code"):
        g = g.reset_index(drop=True)
        g = apply_qfq(g)
        price_data[code] = g

    return price_data, index_df


def run_backtest(
    conn: sqlite3.Connection,
    start: str = "20160101",
    end: str = "20231231",
    initial_cash: float = 1_000_000,
    ma_fast: int = 20,
    ma_slow: int = 60,
    breakout_window: int = 20,
    stop_loss_pct: float = 0.07,
    take_profit_pct: float = 0.15,
    commission: float = 0.00025,
    stamp_duty: float = 0.001,
    slippage: float = 0.002,
    top_n: int = 15,
    max_position_pct: float = 0.15,
    max_risk_per_trade: float = 0.01,
    max_total_exposure: float = 0.60,
    min_volume_20d: float = 50_000_000,
    min_listed_days: int = 365,
) -> dict:
    """
    事件驱动逐日回测。

    返回 dict，含：
      trade_log   — 每笔交易记录 DataFrame
      equity_curve— 每日权益曲线 DataFrame
      metrics     — 绩效指标 dict
    """
    from src.portfolio_manager import Portfolio
    from src.risk_engine import (
        calc_position_size, calc_stop_price, check_portfolio_limits,
        get_strategy_state, check_daily_loss, RiskConfig, StrategyState
    )
    from src.universe_filter import get_universe
    from src.indicators import calc_all_indicators, index_above_ma

    logger.info(f"=== 开始回测 {start} ~ {end} ===")

    # 获取交易日历
    trade_dates = pd.read_sql(
        "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 "
        "AND cal_date>=? AND cal_date<=? ORDER BY cal_date",
        conn, params=[start, end]
    )["cal_date"].tolist()

    if not trade_dates:
        logger.error("无交易日历，请先下载 trade_cal 数据")
        return {}

    logger.info(f"共 {len(trade_dates)} 个交易日")

    # 预加载全量数据
    logger.info("加载历史数据...")
    price_data, index_df = _load_all_price_data(conn, start, end)
    basic_df = pd.read_sql(
        "SELECT ts_code, name, industry, list_date FROM stock_basic", conn
    )

    # 计算指标（按股票预计算）
    logger.info("计算技术指标...")
    for code, df in price_data.items():
        try:
            price_data[code] = calc_all_indicators(
                df, index_df,
                ma_windows=(10, ma_fast, ma_slow),
                breakout_window=breakout_window,
            )
        except Exception as e:
            logger.debug(f"{code} 指标计算失败: {e}")

    # 指数均线过滤序列
    idx_above = index_above_ma(index_df, ma_window=ma_fast)

    portfolio = Portfolio(initial_cash=initial_cash)
    risk_cfg = RiskConfig(
        max_position_pct=max_position_pct,
        max_risk_per_trade=max_risk_per_trade,
        max_total_exposure=max_total_exposure,
    )

    logger.info("开始逐日模拟...")
    for i, date in enumerate(trade_dates):
        if i % 50 == 0:
            logger.debug(f"进度：{date} ({i}/{len(trade_dates)})")

        # 上一个交易日（用于 T+1 成交）
        prev_date = trade_dates[i - 1] if i > 0 else None

        # === 卖出：执行上一日的卖出信号（T+1 开盘价） ===
        if prev_date and hasattr(portfolio, "_pending_sells"):
            for sell in portfolio._pending_sells:
                code = sell["ts_code"]
                df = price_data.get(code, pd.DataFrame())
                today_row = df[df["trade_date"] == date] if not df.empty else pd.DataFrame()
                if not today_row.empty:
                    open_price = today_row.iloc[0].get("open_qfq", today_row.iloc[0].get("open"))
                    exec_price = open_price * (1 - slippage)
                    portfolio.close_position(
                        ts_code=code,
                        exit_date=date,
                        exit_price=exec_price,
                        exit_reason=sell.get("sell_reason", "信号"),
                        commission_rate=commission,
                        stamp_duty_rate=stamp_duty,
                    )

        # === 卖出信号生成（当日收盘后） ===
        current_positions = [
            {
                "ts_code": code,
                "entry_price": pos.entry_price,
                "max_profit_pct": pos.max_profit_pct,
            }
            for code, pos in portfolio.positions.items()
        ]
        sell_signals = generate_sell_signals(
            date, current_positions, price_data,
            ma_fast=ma_fast, ma_exit=10,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        # 更新 max_profit_pct
        for sig in sell_signals:
            code = sig["ts_code"]
            if code in portfolio.positions:
                portfolio.positions[code].max_profit_pct = sig.get("max_profit_pct", 0)
        portfolio._pending_sells = sell_signals

        # === 策略状态检查 ===
        trade_df = portfolio.get_trade_df()
        snap_df = portfolio.get_snapshot_df()
        state = get_strategy_state(trade_df, snap_df, risk_cfg)

        # === 买入信号生成（当日收盘后，T+1 成交） ===
        if state != StrategyState.PAUSED:
            universe = get_universe(date, conn, min_listed_days, min_volume_20d)
            if not universe.empty:
                universe_codes = universe["ts_code"].tolist()
                idx_val = idx_above.get(date, False)

                candidates = generate_buy_signals(
                    date, universe_codes, price_data,
                    index_above_ma=bool(idx_val),
                    ma_slow=ma_slow, ma_fast=ma_fast,
                    breakout_window=breakout_window,
                )
                if not candidates.empty:
                    ranked = rank_signals(candidates, top_n=top_n)
                    portfolio._pending_buys = ranked.to_dict("records")
                else:
                    portfolio._pending_buys = []
            else:
                portfolio._pending_buys = []
        else:
            portfolio._pending_buys = []

        # === 买入：执行上一日的买入信号（T+1 开盘价） ===
        if prev_date and hasattr(portfolio, "_prev_buys"):
            for sig in portfolio._prev_buys:
                code = sig["ts_code"]
                if code in portfolio.positions:
                    continue  # 已持仓跳过
                df = price_data.get(code, pd.DataFrame())
                today_row = df[df["trade_date"] == date] if not df.empty else pd.DataFrame()
                if today_row.empty:
                    continue

                r = today_row.iloc[0]
                # 涨停时不买入（无法成交）
                if r.get("is_limit_up", 0):
                    continue

                open_price = r.get("open_qfq", r.get("open"))
                exec_price = open_price * (1 + slippage)
                ma20_val = r.get(f"ma{ma_fast}", exec_price * 0.93)
                stop_price = calc_stop_price(exec_price, ma20_val, stop_loss_pct)

                # 策略降仓时减半
                adj_risk = max_risk_per_trade * (0.5 if state == StrategyState.HALF else 1.0)
                sizing = calc_position_size(
                    portfolio.cash + sum(
                        pos.market_value(exec_price) for pos in portfolio.positions.values()
                    ),
                    exec_price, stop_price,
                    risk_cfg,
                )
                if sizing["shares"] <= 0:
                    continue

                # 组合限制检查
                basic_row = basic_df[basic_df["ts_code"] == code]
                industry = basic_row.iloc[0]["industry"] if not basic_row.empty else ""
                current_pos_list = [
                    {
                        "ts_code": c,
                        "market_value": pos.market_value(exec_price),
                        "industry": pos.industry,
                    }
                    for c, pos in portfolio.positions.items()
                ]
                account_val = portfolio.cash + sum(p["market_value"] for p in current_pos_list)
                allowed, reason = check_portfolio_limits(
                    account_val, current_pos_list,
                    {"ts_code": code, "industry": industry},
                    sizing["shares"], exec_price, risk_cfg,
                )
                if not allowed:
                    continue

                name = basic_row.iloc[0]["name"] if not basic_row.empty else code
                portfolio.open_position(
                    ts_code=code, name=name, industry=industry,
                    entry_date=date, entry_price=exec_price,
                    shares=sizing["shares"], stop_price=stop_price,
                    commission_rate=commission,
                )

        portfolio._prev_buys = getattr(portfolio, "_pending_buys", [])

        # === 每日快照 ===
        price_map = {}
        for code in portfolio.positions:
            df = price_data.get(code, pd.DataFrame())
            row = df[df["trade_date"] == date] if not df.empty else pd.DataFrame()
            if not row.empty:
                price_map[code] = row.iloc[0].get("close_qfq", row.iloc[0].get("close"))
        portfolio.take_snapshot(date, price_map)

    logger.info("=== 回测完成 ===")

    trade_log = portfolio.get_trade_df()
    equity_curve = portfolio.get_snapshot_df()
    metrics = calc_metrics(equity_curve, trade_log, initial_cash)

    return {
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# 绩效指标
# ---------------------------------------------------------------------------

def calc_metrics(
    equity_curve: pd.DataFrame,
    trade_log: pd.DataFrame,
    initial_cash: float,
    annual_trading_days: int = 252,
) -> dict:
    """计算完整绩效指标。"""
    if equity_curve.empty:
        return {}

    equity = equity_curve["total_equity"]
    returns = equity.pct_change().dropna()

    # 年化收益
    n_days = len(equity)
    total_return = (equity.iloc[-1] / initial_cash) - 1
    annual_return = (1 + total_return) ** (annual_trading_days / max(n_days, 1)) - 1

    # 最大回撤
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_drawdown = drawdown.min()

    # 夏普比率（年化，无风险利率 2%）
    rf_daily = 0.02 / annual_trading_days
    excess = returns - rf_daily
    sharpe = (excess.mean() / excess.std() * np.sqrt(annual_trading_days)
               if excess.std() > 0 else 0)

    metrics: dict = {
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "max_drawdown": round(max_drawdown, 4),
        "sharpe_ratio": round(sharpe, 2),
        "calmar_ratio": round(annual_return / abs(max_drawdown), 2) if max_drawdown != 0 else 0,
        "n_trading_days": n_days,
    }

    if not trade_log.empty:
        metrics["n_trades"] = len(trade_log)
        metrics["win_rate"] = round((trade_log["pnl_pct"] > 0).mean(), 4)
        wins = trade_log.loc[trade_log["pnl_pct"] > 0, "pnl_pct"].mean()
        losses = trade_log.loc[trade_log["pnl_pct"] < 0, "pnl_pct"].mean()
        metrics["avg_win"] = round(wins, 4) if not np.isnan(wins) else 0
        metrics["avg_loss"] = round(losses, 4) if not np.isnan(losses) else 0
        metrics["profit_factor"] = (
            round(abs(wins / losses), 2) if losses != 0 else float("inf")
        )
        metrics["avg_holding_days"] = round(trade_log["holding_days"].mean(), 1)
        metrics["max_consecutive_loss"] = _max_consecutive_loss(trade_log)

    return metrics


def _max_consecutive_loss(trade_log: pd.DataFrame) -> int:
    max_streak = streak = 0
    for pnl in trade_log["pnl_pct"]:
        if pnl < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ---------------------------------------------------------------------------
# 分段回测报告
# ---------------------------------------------------------------------------

_MARKET_PERIODS = {
    "2015熊市": ("20150601", "20160201"),
    "2016震荡": ("20160201", "20170101"),
    "2017蓝筹牛": ("20170101", "20180101"),
    "2018熊市": ("20180101", "20190101"),
    "2019牛市": ("20190101", "20200101"),
    "2020震荡": ("20200101", "20210101"),
    "2021分化": ("20210101", "20220101"),
    "2022熊市": ("20220101", "20230101"),
    "2023震荡": ("20230101", "20240101"),
}


def segment_report(
    equity_curve: pd.DataFrame,
    trade_log: pd.DataFrame,
    initial_cash: float,
) -> pd.DataFrame:
    """按预定义市场阶段输出分段绩效。"""
    rows = []
    for period_name, (s, e) in _MARKET_PERIODS.items():
        eq = equity_curve[
            (equity_curve["date"] >= s) & (equity_curve["date"] <= e)
        ].copy()
        tl = trade_log[
            (trade_log["entry_date"] >= s) & (trade_log["entry_date"] <= e)
        ].copy() if not trade_log.empty else pd.DataFrame()

        if eq.empty:
            continue

        seg_init = eq.iloc[0]["total_equity"]
        m = calc_metrics(eq, tl, seg_init)
        rows.append({
            "期间": period_name,
            "年化收益": f"{m.get('annual_return', 0):.1%}",
            "最大回撤": f"{m.get('max_drawdown', 0):.1%}",
            "夏普": f"{m.get('sharpe_ratio', 0):.2f}",
            "胜率": f"{m.get('win_rate', 0):.1%}",
            "交易次数": m.get("n_trades", 0),
        })

    return pd.DataFrame(rows)
