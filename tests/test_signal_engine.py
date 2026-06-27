"""单元测试：信号生成和排序模块"""

import pandas as pd
import pytest

from src.signal_ranker import rank_signals
from src.signal_engine import generate_buy_signals


def _stock_row(close, ma20, ma60, rs, ma20_up=True, breakout=True, vol_ratio=1.5):
    """构造单只股票在 date 当日的一行（含买入信号所需指标列）。"""
    return pd.DataFrame({
        "trade_date": ["20230101"],
        "close_qfq": [close],
        "ma20": [ma20], "ma60": [ma60], "ma20_up": [ma20_up],
        "breakout_20d": [breakout],
        "vol_ratio_20d": [vol_ratio],
        "rel_strength_20d": [rs],
    })


class TestEntryGates:
    """阶段2 入场质量门槛。基础5条均满足，仅验证新增门槛的剔除行为。"""

    def _universe(self):
        # A: 全合格；B: ma20<ma60（趋势未对齐）；C: rs<0（弱于指数）；D: 过度延伸
        return {
            "A": _stock_row(close=11.0, ma20=10.0, ma60=9.0, rs=5.0),
            "B": _stock_row(close=11.0, ma20=9.0,  ma60=10.0, rs=5.0),
            "C": _stock_row(close=11.0, ma20=10.0, ma60=9.0, rs=-2.0),
            "D": _stock_row(close=13.0, ma20=10.0, ma60=9.0, rs=5.0),  # ext=30%
        }

    def _codes(self):
        return ["A", "B", "C", "D"]

    def test_gates_off_keeps_all(self):
        res = generate_buy_signals("20230101", self._codes(), self._universe(),
                                   index_above_ma=True)
        assert set(res["ts_code"]) == {"A", "B", "C", "D"}

    def test_ma_align_gate(self):
        res = generate_buy_signals("20230101", self._codes(), self._universe(),
                                   index_above_ma=True, require_ma_align=True)
        assert "B" not in set(res["ts_code"])
        assert {"A", "C", "D"}.issubset(set(res["ts_code"]))

    def test_rel_strength_gate(self):
        res = generate_buy_signals("20230101", self._codes(), self._universe(),
                                   index_above_ma=True, min_rel_strength=0.0)
        assert "C" not in set(res["ts_code"])

    def test_extension_gate(self):
        res = generate_buy_signals("20230101", self._codes(), self._universe(),
                                   index_above_ma=True, max_ext_above_ma=0.15)
        assert "D" not in set(res["ts_code"])

    def test_index_below_ma_blocks_all(self):
        res = generate_buy_signals("20230101", self._codes(), self._universe(),
                                   index_above_ma=False)
        assert res.empty


class TestRankSignals:
    def make_candidates(self, n=20):
        return pd.DataFrame({
            "ts_code": [f"{i:06d}.SZ" for i in range(n)],
            "signal_date": ["20230101"] * n,
            "close_qfq": [10 + i * 0.1 for i in range(n)],
            "ma20": [9.5 + i * 0.08 for i in range(n)],
            "ma60": [9.0 + i * 0.05 for i in range(n)],
            "rel_strength_20d": [i * 0.5 for i in range(n)],
            "vol_ratio_20d": [1.0 + i * 0.1 for i in range(n)],
        })

    def test_top_n_limit(self):
        candidates = self.make_candidates(20)
        result = rank_signals(candidates, top_n=10)
        assert len(result) <= 10

    def test_rank_column_exists(self):
        candidates = self.make_candidates(5)
        result = rank_signals(candidates, top_n=5)
        assert "rank" in result.columns
        assert "score" in result.columns

    def test_sorted_by_score(self):
        candidates = self.make_candidates(10)
        result = rank_signals(candidates, top_n=10)
        assert result["score"].is_monotonic_decreasing

    def test_rank_starts_at_one(self):
        candidates = self.make_candidates(5)
        result = rank_signals(candidates, top_n=5)
        assert result["rank"].iloc[0] == 1

    def test_empty_input(self):
        result = rank_signals(pd.DataFrame(), top_n=15)
        assert result.empty

    def test_fewer_than_top_n(self):
        candidates = self.make_candidates(3)
        result = rank_signals(candidates, top_n=15)
        assert len(result) == 3
