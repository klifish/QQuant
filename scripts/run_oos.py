"""
样本外（OOS）回测入口：训练集 + 测试集一次跑完并并排对比。

默认：训练 2015-01～2020-12，测试 2021-01～2025-12（防过拟合，遵循
trading_system_plan.md §9.4）。每段输出绩效指标 + 诊断口径 + 分市场阶段表现。

用法：
  python scripts/run_oos.py
  python scripts/run_oos.py --train-start 20150101 --train-end 20201231 \
                            --test-start 20210101 --test-end 20251231 --cash 1000000
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.config import load_config
from src.backtester import (
    run_backtest, segment_report, calc_diagnostics, format_diagnostics,
)


def _build_kwargs(cfg: dict) -> dict:
    """把 config.yaml 映射为 run_backtest 的关键字参数（与 run_backtest.py 口径一致）。"""
    bt = cfg.get("backtest", {})
    risk = cfg.get("risk", {})
    uni = cfg.get("universe", {})
    kw = {k: v for k, v in cfg.get("strategy", {}).items()
          if k in ("ma_fast", "ma_slow", "breakout_window", "index_ma",
                   "stop_loss_pct", "take_profit_pct", "atr_window", "atr_mult",
                   "use_atr_stop", "require_ma_align", "min_rel_strength",
                   "max_ext_above_ma")}
    kw.update(
        commission=bt.get("commission", 0.00025),
        stamp_duty=bt.get("stamp_duty", 0.001),
        slippage=bt.get("slippage", 0.002),
        top_n=bt.get("top_n_signals", 15),
        max_position_pct=risk.get("max_position_pct", 0.15),
        max_risk_per_trade=risk.get("max_risk_per_trade", 0.01),
        max_total_exposure=risk.get("max_total_exposure", 0.60),
        max_sector_pct=risk.get("max_sector_pct", 0.30),
        max_drawdown_pause=risk.get("max_drawdown_pause", 0.10),
        drawdown_pause_days=risk.get("drawdown_pause_days", 60),
        max_daily_loss=risk.get("max_daily_loss", 0.02),
        consecutive_loss_halve=risk.get("consecutive_loss_halve", 3),
        min_volume_20d=uni.get("min_volume_20d", 50_000_000),
        min_listed_days=uni.get("min_listed_days", 365),
    )
    return kw


_HEADLINE = [
    ("total_return", "总收益", "%"),
    ("annual_return", "年化收益", "%"),
    ("max_drawdown", "最大回撤", "%"),
    ("sharpe_ratio", "夏普", "f"),
    ("calmar_ratio", "卡玛", "f"),
    ("win_rate", "胜率", "%"),
    ("profit_factor", "盈亏比", "f"),
    ("n_trades", "交易数", "d"),
    ("avg_holding_days", "平均持仓天数", "f"),
]


def _report_one(tag: str, start: str, end: str, conn, kwargs: dict, cash: float,
                out_dir: Path, ts: str) -> dict:
    logger.info(f"\n{'='*60}\n[{tag}] 回测 {start} ~ {end}\n{'='*60}")
    res = run_backtest(conn=conn, start=start, end=end, initial_cash=cash, **kwargs)
    if not res:
        logger.error(f"[{tag}] 回测失败（无数据？）")
        return {}

    m = res["metrics"]
    logger.info(f"[{tag}] 绩效:")
    for key, label, fmt in _HEADLINE:
        v = m.get(key, "N/A")
        if isinstance(v, float):
            v = f"{v:.2%}" if fmt == "%" else (f"{v:.2f}" if fmt == "f" else v)
        logger.info(f"    {label}: {v}")

    diag = calc_diagnostics(res["equity_curve"], res["trade_log"], cash)
    logger.info(f"[{tag}] 诊断:\n{format_diagnostics(diag)}")

    seg = segment_report(res["equity_curve"], res["trade_log"], cash)
    if not seg.empty:
        logger.info(f"[{tag}] 分市场阶段:\n{seg.to_string(index=False)}")

    res["equity_curve"].to_csv(out_dir / f"equity_{tag}_{ts}.csv", index=False)
    res["trade_log"].to_csv(out_dir / f"trades_{tag}_{ts}.csv", index=False)
    return m


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="QQuant 样本外回测")
    p.add_argument("--train-start", default="20150101")
    p.add_argument("--train-end", default="20201231")
    p.add_argument("--test-start", default="20210101")
    p.add_argument("--test-end", default="20251231")
    p.add_argument("--cash", type=float, default=1_000_000)
    # 消融开关：覆盖 config，便于一次同步跑多个变体
    p.add_argument("--label", default="", help="输出文件标签（区分变体）")
    p.add_argument("--no-atr-stop", action="store_true", help="关闭 ATR 止损（回退固定%）")
    p.add_argument("--require-ma-align", action="store_true", help="开启趋势对齐门槛")
    p.add_argument("--min-rs", type=float, default=None, help="相对强度硬门槛")
    p.add_argument("--max-ext", type=float, default=None, help="不追过度延伸阈值")
    args = p.parse_args()

    cfg = load_config()
    conn = sqlite3.connect(cfg["data"]["db_path"])
    kwargs = _build_kwargs(cfg)
    if args.no_atr_stop:
        kwargs["use_atr_stop"] = False
    if args.require_ma_align:
        kwargs["require_ma_align"] = True
    if args.min_rs is not None:
        kwargs["min_rel_strength"] = args.min_rs
    if args.max_ext is not None:
        kwargs["max_ext_above_ma"] = args.max_ext
    logger.info(f"变体参数: use_atr_stop={kwargs.get('use_atr_stop', True)}, "
                f"require_ma_align={kwargs.get('require_ma_align', False)}, "
                f"min_rel_strength={kwargs.get('min_rel_strength')}, "
                f"max_ext_above_ma={kwargs.get('max_ext_above_ma')}")

    out_dir = Path("reports/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    if args.label:
        ts = f"{args.label}_{ts}"

    train_m = _report_one("train", args.train_start, args.train_end, conn, kwargs, args.cash, out_dir, ts)
    test_m = _report_one("test", args.test_start, args.test_end, conn, kwargs, args.cash, out_dir, ts)

    logger.info(f"\n{'='*60}\n训练 vs 测试 对比（验收看测试集）\n{'='*60}")
    logger.info(f"{'指标':<14}{'训练':>14}{'测试':>14}")
    for key, label, fmt in _HEADLINE:
        tv, sv = train_m.get(key), test_m.get(key)
        def f(x):
            if isinstance(x, float):
                return f"{x:.2%}" if fmt == "%" else f"{x:.2f}"
            return str(x)
        logger.info(f"{label:<14}{f(tv):>14}{f(sv):>14}")

    conn.close()
    logger.info(f"\n结果已保存至 {out_dir}/ (train/test, 时间戳 {ts})")
