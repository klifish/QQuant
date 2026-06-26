"""
每日报告生成模块：输出 Markdown 格式的交易日报。
"""

from datetime import datetime

import pandas as pd
from loguru import logger


def generate_daily_report(
    date: str,
    portfolio,           # Portfolio 实例
    buy_candidates: pd.DataFrame,
    sell_signals: list[dict],
    price_map: dict[str, float],
    strategy_state: str = "normal",
    anomalies: list[str] | None = None,
    output_path: str | None = None,
) -> str:
    """
    生成每日 Markdown 格式报告。

    参数：
        date           : 报告日期 YYYYMMDD
        portfolio      : Portfolio 实例
        buy_candidates : signal_ranker 输出（Top N DataFrame）
        sell_signals   : signal_engine 输出的卖出信号列表
        price_map      : {ts_code: 当日收盘价}
        strategy_state : "normal" / "half" / "paused"
        anomalies      : 系统异常列表
        output_path    : 若指定则写入文件

    返回：Markdown 字符串
    """
    dt = datetime.strptime(date, "%Y%m%d")
    date_str = dt.strftime("%Y-%m-%d")

    lines = [
        f"# 每日交易报告 — {date_str}",
        "",
        f"**策略状态**：{_state_label(strategy_state)}",
        "",
    ]

    # --- 当前持仓 ---
    lines += ["## 当前持仓", ""]
    if portfolio.positions:
        rows = []
        for code, pos in portfolio.positions.items():
            cur_price = price_map.get(code, pos.entry_price)
            pnl = pos.pnl_pct(cur_price)
            rows.append({
                "代码": code,
                "名称": pos.name,
                "持仓股数": pos.shares,
                "成本价": f"{pos.entry_price:.2f}",
                "现价": f"{cur_price:.2f}",
                "浮盈亏": f"{pnl:.2%}",
                "止损价": f"{pos.stop_price:.2f}",
                "持仓天数": _holding_days(pos.entry_date, date),
            })
        lines.append(_df_to_md(pd.DataFrame(rows)))
    else:
        lines.append("_当前无持仓_")
    lines.append("")

    # --- 今日卖出信号 ---
    lines += ["## 今日卖出信号（T+1 开盘执行）", ""]
    if sell_signals:
        sell_rows = [
            {
                "代码": s["ts_code"],
                "原因": s.get("sell_reason", ""),
                "参考价": f"{s.get('sell_price_ref', 0):.2f}",
                "浮盈亏": f"{s.get('pnl_pct', 0):.2%}",
            }
            for s in sell_signals
        ]
        lines.append(_df_to_md(pd.DataFrame(sell_rows)))
    else:
        lines.append("_无卖出信号_")
    lines.append("")

    # --- 明日买入候选 ---
    lines += ["## 明日买入候选（T+1 开盘参考）", ""]
    if not buy_candidates.empty:
        display_cols = [c for c in [
            "rank", "ts_code", "close_qfq", "score",
            "rel_strength_20d", "vol_ratio_20d"
        ] if c in buy_candidates.columns]
        rename_map = {
            "rank": "排名", "ts_code": "代码",
            "close_qfq": "收盘价（前复权）",
            "score": "评分",
            "rel_strength_20d": "相对强度(%)",
            "vol_ratio_20d": "量比",
        }
        disp = buy_candidates[display_cols].rename(columns=rename_map)
        for col in ["收盘价（前复权）", "相对强度(%)", "量比", "评分"]:
            if col in disp.columns:
                disp[col] = disp[col].round(3)
        lines.append(_df_to_md(disp))
    else:
        lines.append("_无买入候选_")
    lines.append("")

    # --- 账户快照 ---
    snap = portfolio.take_snapshot(date, price_map)
    lines += [
        "## 账户概况", "",
        f"| 项目 | 数值 |",
        f"|---|---|",
        f"| 总权益 | {snap['total_equity']:,.0f} 元 |",
        f"| 现金 | {snap['cash']:,.0f} 元 |",
        f"| 持仓市值 | {snap['position_value']:,.0f} 元 |",
        f"| 总仓位 | {snap['total_exposure']:.1%} |",
        f"| 持仓数量 | {snap['holding_count']} 只 |",
        f"| 累计盈亏 | {snap['total_pnl_pct']:.2%} |",
        f"| 历史最大回撤 | {portfolio.get_max_drawdown():.2%} |",
        "",
    ]

    # --- 历史交易统计 ---
    trade_df = portfolio.get_trade_df()
    if not trade_df.empty:
        lines += [
            "## 历史交易统计", "",
            f"| 项目 | 数值 |",
            f"|---|---|",
            f"| 总交易次数 | {len(trade_df)} |",
            f"| 胜率 | {portfolio.get_win_rate():.1%} |",
            f"| 盈亏比 | {portfolio.get_profit_factor():.2f} |",
            f"| 平均持仓天数 | {trade_df['holding_days'].mean():.1f} 天 |",
            "",
        ]

    # --- 异常日志 ---
    if anomalies:
        lines += ["## 异常日志", ""]
        for a in anomalies:
            lines.append(f"- {a}")
        lines.append("")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"日报已写入：{output_path}")

    return report


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _state_label(state: str) -> str:
    labels = {
        "normal": "✅ 正常（可正常开仓）",
        "half": "⚠️ 降仓（新开仓减半）",
        "paused": "🛑 暂停（不开新仓）",
    }
    return labels.get(state, state)


def _holding_days(entry_date: str, current_date: str) -> int:
    try:
        d1 = datetime.strptime(entry_date, "%Y%m%d")
        d2 = datetime.strptime(current_date, "%Y%m%d")
        return (d2 - d1).days
    except Exception:
        return 0


def _df_to_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_无数据_"
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(df.columns)) + " |"
    rows = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in df.values
    ]
    return "\n".join([header, sep] + rows)
