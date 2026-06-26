"""
持仓管理模块：管理仓位、现金、成交记录。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger


@dataclass
class Position:
    ts_code: str
    name: str
    industry: str
    entry_date: str
    entry_price: float
    shares: int
    stop_price: float
    max_profit_pct: float = 0.0

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares

    def market_value(self, current_price: float) -> float:
        return current_price * self.shares

    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price


@dataclass
class TradeRecord:
    ts_code: str
    name: str
    entry_date: str
    entry_price: float
    shares: int
    exit_date: str
    exit_price: float
    exit_reason: str
    pnl_pct: float
    pnl_amount: float
    holding_days: int
    followed_rule: bool = True
    manual_override: bool = False
    note: str = ""


class Portfolio:
    def __init__(self, initial_cash: float):
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.trade_log: list[TradeRecord] = []
        self.daily_snapshots: list[dict] = []

    # ------------------------------------------------------------------
    # 开仓
    # ------------------------------------------------------------------

    def open_position(
        self,
        ts_code: str,
        name: str,
        industry: str,
        entry_date: str,
        entry_price: float,
        shares: int,
        stop_price: float,
        commission_rate: float = 0.00025,
    ) -> bool:
        cost = entry_price * shares
        commission = cost * commission_rate
        total_cost = cost + commission

        if total_cost > self.cash:
            logger.warning(f"{ts_code} 资金不足：需 {total_cost:.0f}，现金 {self.cash:.0f}")
            return False

        self.cash -= total_cost
        self.positions[ts_code] = Position(
            ts_code=ts_code,
            name=name,
            industry=industry,
            entry_date=entry_date,
            entry_price=entry_price,
            shares=shares,
            stop_price=stop_price,
        )
        logger.info(f"开仓 {name}({ts_code})：{shares}股 @{entry_price:.2f}，成本 {total_cost:.0f}")
        return True

    # ------------------------------------------------------------------
    # 平仓
    # ------------------------------------------------------------------

    def close_position(
        self,
        ts_code: str,
        exit_date: str,
        exit_price: float,
        exit_reason: str,
        commission_rate: float = 0.00025,
        stamp_duty_rate: float = 0.001,
        followed_rule: bool = True,
        manual_override: bool = False,
        note: str = "",
    ) -> Optional[TradeRecord]:
        pos = self.positions.pop(ts_code, None)
        if pos is None:
            logger.warning(f"{ts_code} 不在持仓中")
            return None

        proceeds = exit_price * pos.shares
        commission = proceeds * commission_rate
        stamp_duty = proceeds * stamp_duty_rate
        net_proceeds = proceeds - commission - stamp_duty
        self.cash += net_proceeds

        pnl_amount = net_proceeds - pos.cost
        pnl_pct = pnl_amount / pos.cost

        entry_dt = datetime.strptime(pos.entry_date, "%Y%m%d")
        exit_dt = datetime.strptime(exit_date, "%Y%m%d")
        holding_days = (exit_dt - entry_dt).days

        record = TradeRecord(
            ts_code=ts_code,
            name=pos.name,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            shares=pos.shares,
            exit_date=exit_date,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pct=round(pnl_pct, 4),
            pnl_amount=round(pnl_amount, 2),
            holding_days=holding_days,
            followed_rule=followed_rule,
            manual_override=manual_override,
            note=note,
        )
        self.trade_log.append(record)
        logger.info(
            f"平仓 {pos.name}({ts_code})：@{exit_price:.2f}，"
            f"盈亏 {pnl_pct:.2%}（{pnl_amount:.0f}元），原因：{exit_reason}"
        )
        return record

    # ------------------------------------------------------------------
    # 每日快照
    # ------------------------------------------------------------------

    def take_snapshot(self, date: str, price_map: dict[str, float]) -> dict:
        position_value = sum(
            pos.market_value(price_map.get(code, pos.entry_price))
            for code, pos in self.positions.items()
        )
        total_equity = self.cash + position_value
        snapshot = {
            "date": date,
            "cash": round(self.cash, 2),
            "position_value": round(position_value, 2),
            "total_equity": round(total_equity, 2),
            "total_exposure": round(position_value / total_equity, 4) if total_equity > 0 else 0,
            "holding_count": len(self.positions),
            "total_pnl_pct": round((total_equity - self.initial_cash) / self.initial_cash, 4),
        }
        self.daily_snapshots.append(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_trade_df(self) -> pd.DataFrame:
        if not self.trade_log:
            return pd.DataFrame()
        return pd.DataFrame([vars(r) for r in self.trade_log])

    def get_snapshot_df(self) -> pd.DataFrame:
        if not self.daily_snapshots:
            return pd.DataFrame()
        return pd.DataFrame(self.daily_snapshots)

    def get_win_rate(self) -> float:
        df = self.get_trade_df()
        if df.empty:
            return 0.0
        return (df["pnl_pct"] > 0).mean()

    def get_profit_factor(self) -> float:
        df = self.get_trade_df()
        if df.empty:
            return 0.0
        wins = df.loc[df["pnl_pct"] > 0, "pnl_pct"].sum()
        losses = abs(df.loc[df["pnl_pct"] < 0, "pnl_pct"].sum())
        return round(wins / losses, 2) if losses > 0 else float("inf")

    def get_max_drawdown(self) -> float:
        df = self.get_snapshot_df()
        if df.empty or "total_equity" not in df.columns:
            return 0.0
        equity = df["total_equity"]
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        return round(drawdown.min(), 4)
