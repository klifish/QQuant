"""单元测试：风险管理模块"""

import pandas as pd
import pytest

from src.risk_engine import (
    calc_position_size, calc_stop_price,
    check_portfolio_limits, get_strategy_state,
    check_daily_loss, RiskConfig, StrategyState,
)


class TestPositionSize:
    def test_basic_calculation(self):
        result = calc_position_size(
            account_value=100_000,
            entry_price=20.0,
            stop_price=18.6,
            cfg=RiskConfig(max_risk_per_trade=0.01, max_position_pct=0.15),
        )
        # 可承受亏损 = 1000，每股风险 = 1.4，股数 ≈ 714 → 取整到100倍 = 700
        assert result["shares"] == 700
        assert result["amount"] == pytest.approx(14_000, rel=0.01)

    def test_position_pct_cap(self):
        """单票仓位上限约束。"""
        result = calc_position_size(
            account_value=100_000,
            entry_price=10.0,
            stop_price=9.0,  # 每股风险仅1元，不限制
            cfg=RiskConfig(max_risk_per_trade=0.10, max_position_pct=0.15),
        )
        assert result["position_pct"] <= 0.15 + 0.001  # 允许浮点误差

    def test_entry_equals_stop(self):
        """入场价等于止损价时应返回0仓位。"""
        result = calc_position_size(100_000, 20.0, 20.0)
        assert result["shares"] == 0

    def test_lot_size(self):
        """股数应为100的整数倍。"""
        result = calc_position_size(100_000, 15.0, 14.0)
        assert result["shares"] % 100 == 0

    def test_risk_multiplier_reduces_size(self):
        normal = calc_position_size(
            account_value=100_000,
            entry_price=20.0,
            stop_price=18.0,
            cfg=RiskConfig(max_risk_per_trade=0.02, max_position_pct=1.0),
        )
        reduced = calc_position_size(
            account_value=100_000,
            entry_price=20.0,
            stop_price=18.0,
            cfg=RiskConfig(max_risk_per_trade=0.02, max_position_pct=1.0),
            risk_multiplier=0.5,
        )
        assert reduced["shares"] == normal["shares"] / 2


class TestStopPrice:
    def test_fixed_stop(self):
        """固定止损应不低于入场价的 (1 - stop_loss_pct)。"""
        stop = calc_stop_price(20.0, 22.0, stop_loss_pct=0.07)
        assert stop >= 20.0 * (1 - 0.07) - 0.001

    def test_ma_stop_higher(self):
        """当 MA20 远高于固定止损时，取 MA20 * 0.99。"""
        stop = calc_stop_price(20.0, ma20=19.5, stop_loss_pct=0.07)
        # 固定止损 = 18.6，MA止损 = 19.305，应取较高的 19.305
        assert stop >= 19.3


class TestPortfolioLimits:
    def _make_positions(self, n=4, value=10_000, industry="科技"):
        return [
            {"ts_code": f"00000{i}.SZ", "market_value": value, "industry": industry}
            for i in range(n)
        ]

    def test_total_exposure_block(self):
        """总仓位超限时应拒绝。"""
        positions = self._make_positions(n=5, value=12_000)  # 占60%
        allowed, reason = check_portfolio_limits(
            account_value=100_000,
            current_positions=positions,
            new_signal={"ts_code": "999999.SZ", "industry": "医药"},
            new_shares=100,
            new_entry_price=10.0,  # 新增 1000 元
            cfg=RiskConfig(max_total_exposure=0.60),
        )
        assert not allowed
        assert "总仓位" in reason

    def test_sector_block(self):
        """同行业持仓超限时应拒绝。"""
        positions = self._make_positions(n=3, value=10_000, industry="科技")  # 科技占30%
        allowed, reason = check_portfolio_limits(
            account_value=100_000,
            current_positions=positions,
            new_signal={"ts_code": "999999.SZ", "industry": "科技"},
            new_shares=100,
            new_entry_price=20.0,  # 新增 2000 元科技
            cfg=RiskConfig(max_sector_pct=0.30),
        )
        assert not allowed
        assert "科技" in reason

    def test_allow_normal(self):
        """正常情况下应允许开仓。"""
        allowed, reason = check_portfolio_limits(
            account_value=100_000,
            current_positions=[],
            new_signal={"ts_code": "000001.SZ", "industry": "银行"},
            new_shares=500,
            new_entry_price=20.0,
        )
        assert allowed


class TestStrategyState:
    def test_normal_state(self):
        trade_log = pd.DataFrame({"pnl_pct": [0.05, -0.02, 0.08]})
        account = pd.DataFrame({
            "date": ["20230101", "20230102", "20230103"],
            "equity": [100_000, 101_000, 102_000],
        })
        state = get_strategy_state(trade_log, account)
        assert state == StrategyState.NORMAL

    def test_half_on_consecutive_loss(self):
        trade_log = pd.DataFrame({"pnl_pct": [-0.03, -0.05, -0.04]})
        account = pd.DataFrame({"equity": [100_000, 99_000, 98_000]})
        state = get_strategy_state(
            trade_log, account,
            cfg=RiskConfig(consecutive_loss_halve=3)
        )
        assert state == StrategyState.HALF

    def test_paused_on_drawdown(self):
        equity = [100_000] + [89_000] * 5
        account = pd.DataFrame({"equity": equity})
        state = get_strategy_state(
            pd.DataFrame({"pnl_pct": []}), account,
            cfg=RiskConfig(max_drawdown_pause=0.10)
        )
        assert state == StrategyState.PAUSED

    def test_paused_on_total_equity_drawdown(self):
        account = pd.DataFrame({"total_equity": [100_000, 95_000, 89_000]})
        state = get_strategy_state(
            pd.DataFrame({"pnl_pct": []}), account,
            cfg=RiskConfig(max_drawdown_pause=0.10)
        )
        assert state == StrategyState.PAUSED

    def test_drawdown_pause_overrides_consecutive_loss(self):
        trade_log = pd.DataFrame({"pnl_pct": [-0.03, -0.05, -0.04]})
        account = pd.DataFrame({"total_equity": [100_000, 89_000]})
        state = get_strategy_state(
            trade_log, account,
            cfg=RiskConfig(max_drawdown_pause=0.10, consecutive_loss_halve=3)
        )
        assert state == StrategyState.PAUSED

    def test_can_skip_drawdown_check(self):
        account = pd.DataFrame({"total_equity": [100_000, 89_000]})
        state = get_strategy_state(
            pd.DataFrame({"pnl_pct": []}), account,
            cfg=RiskConfig(max_drawdown_pause=0.10),
            check_drawdown=False,
        )
        assert state == StrategyState.NORMAL


class TestDailyLoss:
    def test_triggers(self):
        assert check_daily_loss(-0.025, RiskConfig(max_daily_loss=0.02))

    def test_no_trigger(self):
        assert not check_daily_loss(-0.01, RiskConfig(max_daily_loss=0.02))
