"""
回测入口脚本。

用法：
  python scripts/run_backtest.py                          # 默认参数
  python scripts/run_backtest.py --start 20180101 --end 20231231
  python scripts/run_backtest.py --validate-only          # 仅做框架验证
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger
from src.config import load_config
from src.backtester import validate_framework, run_backtest, segment_report


def print_metrics(metrics: dict) -> None:
    logger.info("\n=== 回测绩效 ===")
    labels = {
        "total_return": "总收益",
        "annual_return": "年化收益",
        "max_drawdown": "最大回撤",
        "sharpe_ratio": "夏普比率",
        "calmar_ratio": "卡玛比率",
        "n_trades": "总交易次数",
        "win_rate": "胜率",
        "avg_win": "平均盈利",
        "avg_loss": "平均亏损",
        "profit_factor": "盈亏比",
        "avg_holding_days": "平均持仓天数",
        "max_consecutive_loss": "最大连续亏损次数",
    }
    for key, label in labels.items():
        val = metrics.get(key, "N/A")
        if isinstance(val, float) and key not in ("sharpe_ratio", "calmar_ratio", "profit_factor"):
            val = f"{val:.2%}"
        logger.info(f"  {label}: {val}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QQuant 回测工具")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20231231")
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--validate-only", action="store_true",
                        help="仅运行双均线框架验证")
    args = parser.parse_args()

    cfg = load_config()
    conn = sqlite3.connect(cfg["data"]["db_path"])

    if args.validate_only:
        logger.info("运行框架验证（双均线策略）...")
        validate_framework(conn)
        conn.close()
        sys.exit(0)

    logger.info(f"开始回测：{args.start} ~ {args.end}，初始资金：{args.cash:,.0f}")
    results = run_backtest(
        conn=conn,
        start=args.start,
        end=args.end,
        initial_cash=args.cash,
        **{k: v for k, v in cfg.get("strategy", {}).items()
           if k in ("ma_fast", "ma_slow", "breakout_window", "stop_loss_pct", "take_profit_pct")},
        **{k: v for k, v in cfg.get("backtest", {}).items()
           if k in ("commission", "stamp_duty", "slippage", "top_n_signals")},
    )

    if not results:
        logger.error("回测失败，请检查数据")
        conn.close()
        sys.exit(1)

    print_metrics(results["metrics"])

    # 分段报告
    seg = segment_report(
        results["equity_curve"],
        results["trade_log"],
        args.cash,
    )
    if not seg.empty:
        logger.info(f"\n=== 分段绩效 ===\n{seg.to_string(index=False)}")

    # 保存结果
    out_dir = Path("reports/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    results["equity_curve"].to_csv(out_dir / f"equity_{ts}.csv", index=False)
    results["trade_log"].to_csv(out_dir / f"trades_{ts}.csv", index=False)
    logger.info(f"结果已保存至 {out_dir}/")

    conn.close()
