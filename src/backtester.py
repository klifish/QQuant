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

import gc
import sqlite3
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    import vectorbt as vbt
    HAS_VBT = True
except Exception as e:
    vbt = None
    HAS_VBT = False
    logger.warning(f"vectorbt 不可用，validate_framework 功能禁用：{e}")

from src.data_cleaner import apply_qfq
from src.indicators import calc_all_indicators, index_above_ma
from src.signal_engine import generate_buy_signals, generate_sell_signals
from src.signal_ranker import rank_signals


def _index_by_trade_date(df: pd.DataFrame) -> pd.DataFrame:
    """Keep trade_date as a column and also index by it for fast daily lookup."""
    if df.empty or "trade_date" not in df.columns:
        return df
    return df.set_index("trade_date", drop=False)


def _row_on_date(
    price_data: dict[str, pd.DataFrame],
    code: str,
    date: str,
) -> Optional[pd.Series]:
    df = price_data.get(code)
    if df is None or df.empty:
        return None
    if df.index.name == "trade_date":
        if date not in df.index:
            return None
        row = df.loc[date]
        return row.iloc[0] if isinstance(row, pd.DataFrame) else row

    row = df[df["trade_date"] == date]
    if row.empty:
        return None
    return row.iloc[0]


def _last_close_on_or_before(
    price_data: dict[str, pd.DataFrame],
    code: str,
    date: str,
    price_col: str = "close_qfq",
) -> Optional[float]:
    """持仓估值用价：取 date 当日或之前最近一个交易日的收盘价。

    停牌当天该股无 K 线（Tushare 日线对停牌日不返回行），此时不能按当日缺失
    处理为成本价，而应沿用最近一个有效交易日的收盘价冻结估值，避免停牌期间
    权益曲线被错误拉回成本价、复牌时跳变，污染回撤/夏普。
    price_data[code] 已按 trade_date 升序排列。
    """
    df = price_data.get(code)
    if df is None or df.empty:
        return None

    if df.index.name == "trade_date":
        pos = df.index.searchsorted(date, side="right") - 1
        if pos < 0:
            return None
        r = df.iloc[pos]
    else:
        rows = df[df["trade_date"] <= date]
        if rows.empty:
            return None
        r = rows.iloc[-1]

    price = r.get(price_col, r.get(price_col.replace("_qfq", "")))
    if pd.isna(price):
        return None
    return float(price)


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


# ---------------------------------------------------------------------------
# 分段加载（控制峰值内存）：按年加载，统一前复权基准跨段不变
# ---------------------------------------------------------------------------

def _load_base_factors(conn: sqlite3.Connection, end: str) -> dict[str, float]:
    """
    取每只股票在全局 end（含之前最后一个交易日）的复权因子，作为前复权基准。

    全量加载时 apply_qfq 以「窗口内最后一行」为基准；分段加载若每段各自取基准，
    会导致跨段价格水平跳变、持仓盈亏错乱。这里预先算出全局统一基准，
    使任意分段加载得到的前复权价与全量加载完全一致。
    """
    rows = conn.execute(
        "SELECT ts_code, adj_factor FROM stock_daily WHERE trade_date <= ? "
        "GROUP BY ts_code HAVING trade_date = MAX(trade_date)",
        (end,),
    ).fetchall()
    return {code: (f if f else 1.0) for code, f in rows}


def _apply_qfq_base(g: pd.DataFrame, base_factor: float) -> pd.DataFrame:
    """用给定的全局基准因子做前复权（adj_close = close × 当日因子 / base_factor）。

    前复权以最新交易日为锚（base_factor=最新 adj_factor）：最新日 qfq=原始价，
    历史价按 adj_factor/base 缩放，确保跨送转/分红时价格连续（不会凭空跳变）。
    """
    g = g.sort_values("trade_date").reset_index(drop=True)
    if base_factor and "adj_factor" in g.columns and not g["adj_factor"].isna().all():
        ratio = g["adj_factor"] / base_factor
        for raw in ("open", "high", "low", "close"):
            g[f"{raw}_qfq"] = (g[raw] * ratio).round(4)
    else:
        for raw in ("open", "high", "low", "close"):
            g[f"{raw}_qfq"] = g[raw]
    return g


def _load_chunk_price_data(
    conn: sqlite3.Connection,
    load_start: str,
    chunk_end: str,
    base_factors: dict[str, float],
) -> dict[str, pd.DataFrame]:
    """加载 [load_start, chunk_end] 区间全市场日线，用全局基准前复权。"""
    stock_df = pd.read_sql(
        "SELECT * FROM stock_daily WHERE trade_date>=? AND trade_date<=? "
        "ORDER BY ts_code, trade_date",
        conn, params=[load_start, chunk_end],
    )
    price_data: dict[str, pd.DataFrame] = {}
    for code, g in stock_df.groupby("ts_code"):
        price_data[code] = _apply_qfq_base(g, base_factors.get(code, 1.0))
    return price_data


def run_backtest(
    conn: sqlite3.Connection,
    start: str = "20160101",
    end: str = "20231231",
    initial_cash: float = 1_000_000,
    ma_fast: int = 20,
    ma_slow: int = 60,
    breakout_window: int = 20,
    index_ma: int = 20,
    stop_loss_pct: float = 0.07,
    take_profit_pct: float = 0.15,
    commission: float = 0.00025,
    stamp_duty: float = 0.001,
    slippage: float = 0.002,
    top_n: int = 15,
    max_position_pct: float = 0.15,
    max_risk_per_trade: float = 0.01,
    max_total_exposure: float = 0.60,
    max_sector_pct: float = 0.30,
    max_drawdown_pause: float = 0.10,
    drawdown_pause_days: int = 60,
    max_daily_loss: float = 0.02,
    consecutive_loss_halve: int = 3,
    min_volume_20d: float = 50_000_000,
    min_listed_days: int = 365,
    atr_window: int = 14,
    atr_mult: float = 2.5,
    use_atr_stop: bool = True,
    require_ma_align: bool = False,
    min_rel_strength: float | None = None,
    max_ext_above_ma: float | None = None,
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

    # 全市场交易日历（用于计算分段预热的回看起点）
    all_cal = pd.read_sql(
        "SELECT cal_date FROM trade_cal WHERE exchange='SSE' AND is_open=1 ORDER BY cal_date",
        conn
    )["cal_date"].tolist()
    cal_idx = {d: i for i, d in enumerate(all_cal)}
    warmup = max(ma_slow, breakout_window, 20) + 60   # 指标预热所需回看交易日数

    # 全程不变的小数据：股票基础信息 + 全局前复权基准（保证分段价格与全量一致）
    basic_df = pd.read_sql(
        "SELECT ts_code, name, industry, list_date, delist_date FROM stock_basic", conn
    )
    basic_by_code = basic_df.set_index("ts_code").to_dict("index")
    # 退市日映射：到退市日仍持有的标的需强制平仓（退市后再无 K 线，否则仓位卡死）
    delist_map = {
        r["ts_code"]: str(r["delist_date"]).strip()
        for _, r in basic_df.iterrows()
        if pd.notna(r.get("delist_date")) and str(r.get("delist_date")).strip()
    }
    base_factors = _load_base_factors(conn, end)

    # 指数：从首段预热起点加载到 end，保证均线序列有效
    first_load_start = all_cal[max(0, cal_idx.get(trade_dates[0], 0) - warmup)]
    index_df = pd.read_sql(
        "SELECT * FROM index_daily WHERE ts_code='399300.SZ' "
        "AND trade_date>=? AND trade_date<=? ORDER BY trade_date",
        conn, params=[first_load_start, end],
    )
    idx_above = index_above_ma(index_df, ma_window=index_ma)

    # 分段加载：按自然年分块，仅跨年时重载，峰值内存 ≈ 单年体量
    price_data: dict[str, pd.DataFrame] = {}
    loaded_year: Optional[str] = None

    portfolio = Portfolio(initial_cash=initial_cash)
    risk_cfg = RiskConfig(
        max_position_pct=max_position_pct,
        max_risk_per_trade=max_risk_per_trade,
        max_total_exposure=max_total_exposure,
        max_sector_pct=max_sector_pct,
        max_drawdown_pause=max_drawdown_pause,
        drawdown_pause_days=drawdown_pause_days,
        max_daily_loss=max_daily_loss,
        consecutive_loss_halve=consecutive_loss_halve,
    )

    drawdown_pause_until_idx = -1
    drawdown_pause_armed = True

    logger.info("开始逐日模拟...")
    for i, date in enumerate(trade_dates):
        if i % 50 == 0:
            logger.debug(f"进度：{date} ({i}/{len(trade_dates)})")

        # 跨年时重载该年数据（含预热回看）并释放上一年，控制峰值内存
        year = date[:4]
        if year != loaded_year:
            price_data.clear()
            gc.collect()
            load_start = all_cal[max(0, cal_idx.get(date, 0) - warmup)]
            chunk_end = min(f"{year}1231", end)
            logger.info(f"加载 {year} 年数据（预热自 {load_start}）...")
            price_data = _load_chunk_price_data(conn, load_start, chunk_end, base_factors)
            for code, df in price_data.items():
                try:
                    price_data[code] = _index_by_trade_date(calc_all_indicators(
                        df, index_df,
                        ma_windows=(10, ma_fast, ma_slow),
                        breakout_window=breakout_window,
                        vol_window=breakout_window,
                        rs_window=breakout_window,
                        atr_window=atr_window,
                    ))
                except Exception as e:
                    logger.debug(f"{code} 指标计算失败: {e}")
            loaded_year = year

        # 上一个交易日（用于 T+1 成交）
        prev_date = trade_dates[i - 1] if i > 0 else None

        # === 卖出：执行上一日的卖出信号（T+1 开盘价） ===
        if prev_date and hasattr(portfolio, "_pending_sells"):
            for sell in portfolio._pending_sells:
                code = sell["ts_code"]
                r = _row_on_date(price_data, code, date)
                if r is not None:
                    open_price = r.get("open_qfq", r.get("open"))
                    exec_price = open_price * (1 - slippage)
                    portfolio.close_position(
                        ts_code=code,
                        exit_date=date,
                        exit_price=exec_price,
                        exit_reason=sell.get("sell_reason", "信号"),
                        commission_rate=commission,
                        stamp_duty_rate=stamp_duty,
                    )

        # === 退市强平：到退市日仍持有的，按最后有效收盘价强制平仓 ===
        # 退市后该股再无 K 线，普通卖出信号永远取不到行而跳过，会导致仓位卡死、
        # 现金不回笼、净值虚高。这里在退市日（或之后首个交易日）强制了结。
        for code in list(portfolio.positions.keys()):
            dl = delist_map.get(code)
            if dl and date >= dl:
                last_close = _last_close_on_or_before(price_data, code, date)
                exit_price = (
                    last_close if last_close is not None
                    else portfolio.positions[code].entry_price
                )
                portfolio.close_position(
                    ts_code=code,
                    exit_date=date,
                    exit_price=exit_price,
                    exit_reason="退市强平",
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
        # generate_sell_signals 会更新传入持仓 dict 的 max_profit_pct；
        # 无论是否触发卖出，都要写回组合，保证移动止盈用的是历史最大浮盈。
        for pos_info in current_positions:
            code = pos_info["ts_code"]
            if code in portfolio.positions:
                portfolio.positions[code].max_profit_pct = pos_info.get("max_profit_pct", 0)
        portfolio._pending_sells = sell_signals

        # === 策略状态检查 ===
        trade_df = portfolio.get_trade_df()
        snap_df = portfolio.get_snapshot_df()
        state = get_strategy_state(trade_df, snap_df, risk_cfg, check_drawdown=False)

        if not snap_df.empty:
            equity = snap_df["total_equity"]
            peak = equity.cummax().iloc[-1]
            current_drawdown = (equity.iloc[-1] - peak) / peak if peak > 0 else 0

            if current_drawdown > -risk_cfg.max_drawdown_pause * 0.5:
                drawdown_pause_armed = True

            if (
                drawdown_pause_armed
                and current_drawdown <= -risk_cfg.max_drawdown_pause
            ):
                drawdown_pause_until_idx = i + risk_cfg.drawdown_pause_days
                drawdown_pause_armed = False
                logger.warning(
                    f"当前回撤 {current_drawdown:.1%}，暂停开仓 "
                    f"{risk_cfg.drawdown_pause_days} 个交易日"
                )

        if i <= drawdown_pause_until_idx:
            state = StrategyState.PAUSED

        # === 单日亏损熔断：当日浮动亏损超限则今日不再开仓 ===
        # 以"当日盯市权益 vs 昨日收盘权益"的跌幅近似当日亏损。
        if state != StrategyState.PAUSED and not snap_df.empty:
            prev_equity = snap_df["total_equity"].iloc[-1]
            cur_equity = portfolio.cash + sum(
                pos.market_value(
                    _last_close_on_or_before(price_data, c, date) or pos.entry_price
                )
                for c, pos in portfolio.positions.items()
            )
            if prev_equity > 0 and check_daily_loss(
                (cur_equity - prev_equity) / prev_equity, risk_cfg
            ):
                logger.warning(
                    f"{date} 当日亏损超 {risk_cfg.max_daily_loss:.0%}，今日暂停开仓"
                )
                state = StrategyState.PAUSED

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
                    require_ma_align=require_ma_align,
                    min_rel_strength=min_rel_strength,
                    max_ext_above_ma=max_ext_above_ma,
                )
                if not candidates.empty:
                    ranked = rank_signals(
                        candidates,
                        top_n=top_n,
                        rs_window=breakout_window,
                        vol_window=breakout_window,
                    )
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
                r = _row_on_date(price_data, code, date)
                if r is None:
                    continue

                # 涨停时不买入（无法成交）
                if r.get("is_limit_up", 0):
                    continue

                open_price = r.get("open_qfq", r.get("open"))
                exec_price = open_price * (1 + slippage)
                ma20_val = r.get(f"ma{ma_fast}", exec_price * 0.93)
                atr_val = r.get(f"atr{atr_window}") if use_atr_stop else None
                stop_price = calc_stop_price(
                    exec_price, ma20_val, stop_loss_pct,
                    atr=atr_val, atr_mult=atr_mult,
                )

                # 策略降仓时减半
                risk_multiplier = 0.5 if state == StrategyState.HALF else 1.0
                sizing = calc_position_size(
                    portfolio.cash + sum(
                        pos.market_value(_last_close_on_or_before(price_data, code, date) or pos.entry_price)
                        for code, pos in portfolio.positions.items()
                    ),
                    exec_price, stop_price,
                    risk_cfg,
                    risk_multiplier=risk_multiplier,
                )
                if sizing["shares"] <= 0:
                    continue

                # 组合限制检查
                basic_info = basic_by_code.get(code, {})
                industry = basic_info.get("industry", "")
                current_pos_list = [
                    {
                        "ts_code": c,
                        "market_value": pos.market_value(
                            _last_close_on_or_before(price_data, c, date) or pos.entry_price
                        ),
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

                name = basic_info.get("name", code)
                portfolio.open_position(
                    ts_code=code, name=name, industry=industry,
                    entry_date=date, entry_price=exec_price,
                    shares=sizing["shares"], stop_price=stop_price,
                    commission_rate=commission,
                )

        portfolio._prev_buys = getattr(portfolio, "_pending_buys", [])

        # === 每日快照 ===
        # 停牌日无当日 K 线时，沿用最近有效收盘价估值（而非回退成本价），
        # 避免停牌期间权益曲线被错误拉回成本、复牌时跳变。
        price_map = {}
        for code in portfolio.positions:
            last_close = _last_close_on_or_before(price_data, code, date)
            if last_close is not None:
                price_map[code] = last_close
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
    excess_std = excess.std()
    sharpe = (
        excess.mean() / excess_std * np.sqrt(annual_trading_days)
        if excess_std > 1e-12 else 0
    )

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
    "2024震荡": ("20240101", "20250101"),
    "2025至今": ("20250101", "20251231"),
}


def _exit_reason_category(reason: str) -> str:
    """把退出原因归并为大类，便于统计分布。"""
    r = str(reason)
    if r.startswith("止损"):
        return "止损"
    if r.startswith("盈利后跌破"):
        return "移动止盈"
    if "跌破" in r:
        return "趋势破坏"
    if "退市" in r:
        return "退市强平"
    return "其他"


def calc_diagnostics(
    equity_curve: pd.DataFrame,
    trade_log: pd.DataFrame,
    initial_cash: float,
    cost_per_turn: float = 0.0095,
    annual_trading_days: int = 252,
) -> dict:
    """
    诊断口径：聚焦"为什么死/活"的可执行指标，补 calc_metrics 之外的视角。

    返回：
      expectancy        — 单笔扣费后平均收益率（pnl_pct 均值，已含卖出侧成本）
      turnover_annual   — 年化换手率（买入名义额 / 平均权益 / 年数）
      cost_drag_annual  — 估算的年化成本拖累（换手 × 双向成本率）
      avg_exposure      — 平均总仓位
      avg_holding_count — 平均持仓只数（部署率参考）
      exit_breakdown    — 退出原因大类占比 dict
      by_year           — 分年 DataFrame：交易数/胜率/单笔期望
    """
    diag: dict = {}
    if equity_curve.empty:
        return diag

    n_days = len(equity_curve)
    years = max(n_days / annual_trading_days, 1e-9)
    avg_equity = equity_curve["total_equity"].mean()
    diag["avg_exposure"] = round(equity_curve.get("total_exposure", pd.Series([0])).mean(), 4)
    diag["avg_holding_count"] = round(equity_curve.get("holding_count", pd.Series([0])).mean(), 2)

    if trade_log.empty:
        diag["expectancy"] = 0.0
        diag["turnover_annual"] = 0.0
        diag["cost_drag_annual"] = 0.0
        diag["exit_breakdown"] = {}
        diag["by_year"] = pd.DataFrame()
        return diag

    tl = trade_log.copy()
    diag["expectancy"] = round(tl["pnl_pct"].mean(), 4)

    # 换手与成本拖累：以买入名义额近似单边换手
    buy_notional = (tl["entry_price"] * tl["shares"]).sum()
    turnover_annual = buy_notional / avg_equity / years if avg_equity > 0 else 0
    diag["turnover_annual"] = round(turnover_annual, 2)
    diag["cost_drag_annual"] = round(turnover_annual * cost_per_turn, 4)

    cat = tl["exit_reason"].map(_exit_reason_category)
    diag["exit_breakdown"] = {
        k: round(v, 3) for k, v in cat.value_counts(normalize=True).items()
    }

    tl["yr"] = tl["entry_date"].astype(str).str[:4]
    by_year = tl.groupby("yr").apply(
        lambda g: pd.Series({
            "交易数": len(g),
            "胜率": round((g["pnl_pct"] > 0).mean(), 3),
            "单笔期望": round(g["pnl_pct"].mean(), 4),
        }),
        include_groups=False,
    ).reset_index()
    diag["by_year"] = by_year

    return diag


def format_diagnostics(diag: dict) -> str:
    """把 calc_diagnostics 的结果格式化为可读文本块。"""
    if not diag:
        return "（无诊断数据）"
    lines = [
        f"  单笔扣费后期望: {diag.get('expectancy', 0):+.2%}",
        f"  年化换手率:     {diag.get('turnover_annual', 0):.2f}",
        f"  估算年化成本拖累: {diag.get('cost_drag_annual', 0):.2%}",
        f"  平均总仓位:     {diag.get('avg_exposure', 0):.1%}",
        f"  平均持仓只数:   {diag.get('avg_holding_count', 0):.1f}",
        f"  退出原因占比:   {diag.get('exit_breakdown', {})}",
    ]
    by_year = diag.get("by_year")
    if by_year is not None and not by_year.empty:
        lines.append("  分年表现:")
        for _, r in by_year.iterrows():
            lines.append(
                f"    {r['yr']}: {int(r['交易数']):3d} 笔 | "
                f"胜率 {r['胜率']:.0%} | 期望 {r['单笔期望']:+.2%}"
            )
    return "\n".join(lines)


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
