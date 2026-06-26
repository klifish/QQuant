"""单元测试：信号生成和排序模块"""

import pandas as pd
import pytest

from src.signal_ranker import rank_signals


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
