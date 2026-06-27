"""
风险管理模块：仓位计算、风险检查、熔断机制。
"""

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
from loguru import logger


class StrategyState(str, Enum):
    NORMAL = "normal"   # 正常开仓
    HALF = "half"       # 降仓（新开仓减半）
    PAUSED = "paused"   # 暂停开仓


@dataclass
class RiskConfig:
    max_position_pct: float = 0.15       # 单票最大仓位
    max_risk_per_trade: float = 0.01     # 单笔最大账户风险
    max_total_exposure: float = 0.60     # 总仓位上限
    max_sector_pct: float = 0.30         # 同行业上限
    max_drawdown_pause: float = 0.10     # 最大回撤暂停线
    drawdown_pause_days: int = 60        # 回撤触发后暂停开仓的交易日数
    max_daily_loss: float = 0.02         # 单日最大亏损
    consecutive_loss_halve: int = 3      # 连续亏损N笔后降仓


# ---------------------------------------------------------------------------
# 仓位计算
# ---------------------------------------------------------------------------

def calc_position_size(
    account_value: float,
    entry_price: float,
    stop_price: float,
    cfg: RiskConfig | None = None,
    risk_multiplier: float = 1.0,
    lot_size: int = 100,
) -> dict:
    """
    根据固定风险法计算最大持仓股数。

    公式：
      可承受亏损 = account_value × max_risk_per_trade
      股数 = 可承受亏损 / (entry_price - stop_price)

    返回 dict：shares, amount, position_pct, risk_amount
    """
    if cfg is None:
        cfg = RiskConfig()

    if entry_price <= stop_price:
        return {"shares": 0, "amount": 0, "position_pct": 0, "risk_amount": 0}

    risk_multiplier = max(risk_multiplier, 0.0)
    risk_amount = account_value * cfg.max_risk_per_trade * risk_multiplier
    risk_per_share = entry_price - stop_price
    raw_shares = risk_amount / risk_per_share

    # 向下取整到 lot_size（A股100股一手）
    shares = int(raw_shares / lot_size) * lot_size

    # 不超过单票仓位上限
    max_shares_by_pct = int(
        (account_value * cfg.max_position_pct / entry_price) / lot_size
    ) * lot_size
    shares = min(shares, max_shares_by_pct)

    amount = shares * entry_price
    position_pct = amount / account_value

    return {
        "shares": shares,
        "amount": round(amount, 2),
        "position_pct": round(position_pct, 4),
        "risk_amount": round(shares * risk_per_share, 2),
    }


# ---------------------------------------------------------------------------
# 止损价计算
# ---------------------------------------------------------------------------

def calc_stop_price(
    entry_price: float,
    ma20: float,
    stop_loss_pct: float = 0.07,
) -> float:
    """
    止损价 = max(entry × (1 - stop_loss_pct), ma20 × 0.99)
    取更高的那个，保护更严格。
    """
    fixed_stop = entry_price * (1 - stop_loss_pct)
    ma_stop = ma20 * 0.99
    return round(max(fixed_stop, ma_stop), 4)


# ---------------------------------------------------------------------------
# 组合限制检查
# ---------------------------------------------------------------------------

def check_portfolio_limits(
    account_value: float,
    current_positions: list[dict],
    new_signal: dict,
    new_shares: int,
    new_entry_price: float,
    cfg: RiskConfig | None = None,
) -> tuple[bool, str]:
    """
    检查加入新持仓后是否违反组合限制。

    参数：
        current_positions : 现有持仓列表，每项含 ts_code, market_value, industry
        new_signal        : 买入信号，含 ts_code, industry
        new_shares / new_entry_price : 新仓位

    返回：(是否允许开仓, 拒绝原因)
    """
    if cfg is None:
        cfg = RiskConfig()

    new_value = new_shares * new_entry_price
    current_exposure = sum(p.get("market_value", 0) for p in current_positions)
    total_exposure = current_exposure + new_value

    # 总仓位上限
    if total_exposure / account_value > cfg.max_total_exposure:
        return False, f"总仓位 {total_exposure/account_value:.1%} 超过上限 {cfg.max_total_exposure:.0%}"

    # 行业集中度
    industry = new_signal.get("industry", "")
    if industry:
        sector_value = sum(
            p.get("market_value", 0)
            for p in current_positions
            if p.get("industry") == industry
        ) + new_value
        if sector_value / account_value > cfg.max_sector_pct:
            return False, f"行业 '{industry}' 持仓 {sector_value/account_value:.1%} 超过上限 {cfg.max_sector_pct:.0%}"

    # 单票重复开仓检查
    existing_codes = {p["ts_code"] for p in current_positions}
    if new_signal["ts_code"] in existing_codes:
        return False, f"{new_signal['ts_code']} 已在持仓中"

    return True, ""


# ---------------------------------------------------------------------------
# 熔断机制（策略状态）
# ---------------------------------------------------------------------------

def get_strategy_state(
    trade_log: pd.DataFrame,
    account_history: pd.DataFrame,
    cfg: RiskConfig | None = None,
    check_drawdown: bool = True,
) -> StrategyState:
    """
    根据交易记录和账户历史判断当前策略状态。

    参数：
        trade_log       : 含 pnl_pct 列（每笔交易的盈亏）
        account_history : 含 date, equity 列（每日账户权益）
        cfg             : 风险配置

    返回：StrategyState
    """
    if cfg is None:
        cfg = RiskConfig()

    # 最大回撤是组合级风险，应优先于连续亏损降仓。
    equity_col = None
    for col in ("total_equity", "equity"):
        if col in account_history.columns:
            equity_col = col
            break

    if check_drawdown and not account_history.empty and equity_col:
        equity = account_history[equity_col]
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        current_dd = drawdown.iloc[-1]
        if current_dd <= -cfg.max_drawdown_pause:
            logger.warning(f"当前回撤 {current_dd:.1%}，暂停开仓")
            return StrategyState.PAUSED

    # 连续亏损检查
    if not trade_log.empty:
        recent = trade_log["pnl_pct"].tail(cfg.consecutive_loss_halve)
        if len(recent) == cfg.consecutive_loss_halve and (recent < 0).all():
            logger.warning(f"连续 {cfg.consecutive_loss_halve} 笔亏损，降仓模式")
            return StrategyState.HALF

    return StrategyState.NORMAL


def check_daily_loss(
    daily_pnl_pct: float,
    cfg: RiskConfig | None = None,
) -> bool:
    """当日亏损超过阈值时返回 True（表示今日不再开仓）。"""
    if cfg is None:
        cfg = RiskConfig()
    return daily_pnl_pct <= -cfg.max_daily_loss
