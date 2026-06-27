"""
信号生成模块。

买入信号（5个条件全部满足）：
  1. close_qfq > ma60
  2. ma20 向上（ma20_up = True）
  3. close_qfq 突破过去20日最高价（breakout_20d = True）
  4. 当日成交额 > 过去20日平均成交额（vol_ratio_20d > 1）
  5. 大盘（沪深300）在20日均线之上

卖出信号（满足任一即触发）：
  1. close_qfq 跌破 ma20
  2. 亏损超过 stop_loss_pct（默认 7%）
  3. 最大盈利曾超过 take_profit_pct（默认15%）后又跌破 ma10

关键约定：
  - 信号基于 T 日收盘数据生成，T+1 开盘成交
  - 不使用任何 T 日之后的数据（严防未来函数）
"""

import pandas as pd
from loguru import logger


def _row_on_date(df: pd.DataFrame, date: str) -> pd.Series | None:
    """Fast date lookup; price frames may be indexed by trade_date."""
    if df.empty:
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


# ---------------------------------------------------------------------------
# 买入信号
# ---------------------------------------------------------------------------

def generate_buy_signals(
    date: str,
    universe_codes: list[str],
    price_data: dict[str, pd.DataFrame],
    index_above_ma: bool,
    ma_slow: int = 60,
    ma_fast: int = 20,
    breakout_window: int = 20,
) -> pd.DataFrame:
    """
    生成指定日期的买入候选列表。

    参数：
        date            : 信号日期（T日），格式 YYYYMMDD
        universe_codes  : 当日可交易股票列表
        price_data      : dict[ts_code -> DataFrame]，每只股票含指标列
        index_above_ma  : 大盘是否在均线上方（布尔）
        ma_slow/fast    : 均线周期
        breakout_window : 突破窗口

    返回：
        DataFrame，列：ts_code, close_qfq, ma{fast}, ma{slow},
                       breakout_{w}d, vol_ratio_{w}d, rel_strength_{w}d
    """
    if not index_above_ma:
        logger.debug(f"{date} 大盘在均线下方，无买入信号")
        return pd.DataFrame()

    candidates = []
    for code in universe_codes:
        df = price_data.get(code)
        if df is None or df.empty:
            continue

        r = _row_on_date(df, date)
        if r is None:
            continue

        # 检查必要列是否存在且有效
        needed = [
            f"ma{ma_fast}", f"ma{ma_slow}",
            f"ma{ma_fast}_up", f"breakout_{breakout_window}d",
            f"vol_ratio_{breakout_window}d",
        ]
        if any(pd.isna(r.get(col)) for col in needed):
            continue

        # 条件1：收盘价在慢线上方
        if r["close_qfq"] <= r[f"ma{ma_slow}"]:
            continue
        # 条件2：快线向上
        if not r[f"ma{ma_fast}_up"]:
            continue
        # 条件3：突破 N 日最高价
        if not r[f"breakout_{breakout_window}d"]:
            continue
        # 条件4：量比 > 1
        vol_ratio = r.get(f"vol_ratio_{breakout_window}d", 0)
        if pd.isna(vol_ratio) or vol_ratio <= 1.0:
            continue

        candidates.append({
            "ts_code": code,
            "signal_date": date,
            "close_qfq": r["close_qfq"],
            f"ma{ma_fast}": r[f"ma{ma_fast}"],
            f"ma{ma_slow}": r[f"ma{ma_slow}"],
            f"breakout_{breakout_window}d": r[f"breakout_{breakout_window}d"],
            f"vol_ratio_{breakout_window}d": vol_ratio,
            f"rel_strength_{breakout_window}d": r.get(f"rel_strength_{breakout_window}d", 0),
        })

    result = pd.DataFrame(candidates)
    logger.info(f"{date} 买入候选（过滤前）：{len(result)} 只")
    return result


# ---------------------------------------------------------------------------
# 卖出信号
# ---------------------------------------------------------------------------

def generate_sell_signals(
    date: str,
    positions: list[dict],
    price_data: dict[str, pd.DataFrame],
    ma_fast: int = 20,
    ma_exit: int = 10,
    stop_loss_pct: float = 0.07,
    take_profit_pct: float = 0.15,
) -> list[dict]:
    """
    对当前持仓逐一检查卖出条件。

    参数：
        date          : 检查日期（T日）
        positions     : 持仓列表，每项含 ts_code, entry_price, max_profit_pct
        price_data    : 价格数据
        ma_fast       : 主要出场均线（ma20）
        ma_exit       : 止盈后移动止损均线（ma10）
        stop_loss_pct : 固定止损比例
        take_profit_pct: 触发移动止损的盈利阈值

    返回：
        触发卖出的持仓列表，每项新增 sell_reason 字段
    """
    sell_list = []

    for pos in positions:
        code = pos["ts_code"]
        df = price_data.get(code)
        if df is None or df.empty:
            continue

        r = _row_on_date(df, date)
        if r is None:
            continue

        close = r.get("close_qfq", r.get("close"))
        if pd.isna(close):
            continue

        entry_price = pos["entry_price"]
        pnl_pct = (close - entry_price) / entry_price
        max_pnl = pos.get("max_profit_pct", pnl_pct)

        # 更新最大盈利
        pos["max_profit_pct"] = max(max_pnl, pnl_pct)

        reason = None

        # 条件1：固定止损
        if pnl_pct <= -stop_loss_pct:
            reason = f"止损 {pnl_pct:.1%}"

        # 条件2：跌破快线（ma20）
        elif not pd.isna(r.get(f"ma{ma_fast}")) and close < r[f"ma{ma_fast}"]:
            reason = f"跌破MA{ma_fast}"

        # 条件3：曾盈利超过阈值后跌破 ma_exit（ma10）
        elif (
            pos.get("max_profit_pct", 0) >= take_profit_pct
            and not pd.isna(r.get(f"ma{ma_exit}"))
            and close < r[f"ma{ma_exit}"]
        ):
            reason = f"盈利后跌破MA{ma_exit}"

        if reason:
            sell_info = dict(pos)
            sell_info["sell_date"] = date
            sell_info["sell_price_ref"] = close  # 参考价，实际按次日开盘
            sell_info["pnl_pct"] = pnl_pct
            sell_info["sell_reason"] = reason
            sell_list.append(sell_info)

    logger.info(f"{date} 卖出信号：{len(sell_list)} 只")
    return sell_list
