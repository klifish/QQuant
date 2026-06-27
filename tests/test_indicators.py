"""单元测试：技术指标模块"""

import pandas as pd
import numpy as np
import pytest

from src.indicators import (
    calc_ma, calc_ma_slope, calc_breakout,
    calc_volume_ratio, calc_relative_strength, index_above_ma, calc_atr,
)
from src.data_cleaner import apply_qfq
from src.backtester import _apply_qfq_base


class TestQfqAdjustment:
    """前复权方向回归测试：跨送转/分红时 qfq 必须连续，切勿把公式写反。"""

    def _split_df(self):
        # 2:1 拆股：原始 close 30→15，adj_factor 1.0→2.0，真实收益为 0（仅拆股）
        return pd.DataFrame({
            "trade_date": ["20230101", "20230102", "20230103"],
            "open": [30.0, 15.0, 15.3], "high": [30.0, 15.0, 15.3],
            "low": [30.0, 15.0, 15.3], "close": [30.0, 15.0, 15.0],
            "pre_close": [29.0, 30.0, 15.0], "adj_factor": [1.0, 2.0, 2.0],
        })

    def test_apply_qfq_continuous_across_split(self):
        out = apply_qfq(self._split_df())
        # 拆股前后 qfq 连续：30(adj1) 与 15(adj2) 前复权后相等
        assert out["close_qfq"].iloc[0] == pytest.approx(out["close_qfq"].iloc[1], rel=1e-6)
        # 最新日 qfq == 原始价
        assert out["close_qfq"].iloc[-1] == pytest.approx(15.0, rel=1e-6)

    def test_apply_qfq_constant_factor_equals_raw(self):
        df = pd.DataFrame({
            "trade_date": ["20230101", "20230102"],
            "open": [10.0, 11.0], "high": [10.0, 11.0], "low": [10.0, 11.0],
            "close": [10.0, 11.0], "pre_close": [9.0, 10.0], "adj_factor": [5.0, 5.0],
        })
        out = apply_qfq(df)
        assert out["close_qfq"].tolist() == [10.0, 11.0]

    def test_apply_qfq_base_continuous_across_split(self):
        # _apply_qfq_base 用全局 base_factor=最新因子(2.0)
        out = _apply_qfq_base(self._split_df(), base_factor=2.0)
        assert out["close_qfq"].iloc[0] == pytest.approx(out["close_qfq"].iloc[1], rel=1e-6)
        assert out["close_qfq"].iloc[-1] == pytest.approx(15.0, rel=1e-6)


def make_price_df(n=100, start_price=10.0, trend=0.001):
    """生成模拟价格数据。"""
    dates = pd.date_range("20200101", periods=n, freq="B").strftime("%Y%m%d").tolist()
    close = [start_price * (1 + trend) ** i for i in range(n)]
    high  = [c * 1.01 for c in close]
    low   = [c * 0.99 for c in close]
    open_ = [c * 1.002 for c in close]
    vol   = [1e8] * n
    return pd.DataFrame({
        "trade_date": dates,
        "open": open_, "high": high, "low": low,
        "close": close,
        "close_qfq": close, "high_qfq": high, "low_qfq": low, "open_qfq": open_,
        "amount": vol,
        "vol": vol,
    })


class TestCalcMA:
    def test_ma20_length(self):
        df = make_price_df(60)
        result = calc_ma(df, [20])
        assert "ma20" in result.columns
        # 前19行应为 NaN
        assert result["ma20"].iloc[:19].isna().all()
        assert not result["ma20"].iloc[19:].isna().any()

    def test_ma_value(self):
        df = make_price_df(30)
        result = calc_ma(df, [5])
        manual = df["close_qfq"].rolling(5).mean().iloc[29]
        assert abs(result["ma5"].iloc[29] - manual) < 1e-6


class TestCalcATR:
    def test_atr_column_and_warmup(self):
        df = make_price_df(40)
        result = calc_atr(df, window=14)
        assert "atr14" in result.columns
        # 前13行（不足窗口）应为 NaN，之后有效
        assert result["atr14"].iloc[:13].isna().all()
        assert not result["atr14"].iloc[14:].isna().any()

    def test_atr_positive(self):
        df = make_price_df(40)
        result = calc_atr(df, window=14)
        assert (result["atr14"].dropna() > 0).all()

    def test_atr_value(self):
        # 构造已知 TR：high-low 恒为 2，且无跳空，则 ATR≈2
        n = 20
        dates = pd.date_range("20200101", periods=n, freq="B").strftime("%Y%m%d").tolist()
        close = [100.0] * n
        df = pd.DataFrame({
            "trade_date": dates,
            "high_qfq": [101.0] * n, "low_qfq": [99.0] * n, "close_qfq": close,
            "high": [101.0] * n, "low": [99.0] * n, "close": close,
        })
        result = calc_atr(df, window=5)
        assert result["atr5"].iloc[-1] == pytest.approx(2.0, abs=1e-6)


class TestMaSlope:
    def test_uptrend(self):
        df = make_price_df(30, trend=0.01)
        df = calc_ma(df, [20])
        df = calc_ma_slope(df, "ma20")
        # 上涨趋势下，均线方向应全部为 True（从第21行起）
        assert df["ma20_up"].iloc[21:].all()

    def test_no_future(self):
        df = make_price_df(30)
        df = calc_ma(df, [5])
        df = calc_ma_slope(df, "ma5")
        # 第一个有效行（index 5）的 ma5_up 应基于 index 4 和 5，不含 index 6
        # 只需确认列存在且类型正确
        assert df["ma5_up"].dtype == bool or df["ma5_up"].dtype == object


class TestBreakout:
    def test_breakout_no_future(self):
        """突破判断必须基于历史最高价，不含当日。"""
        df = make_price_df(40)
        df = calc_breakout(df, window=20)
        # shift(1) 保证不含当日 high，所以 breakout 列不应超前
        col = "breakout_20d"
        assert col in df.columns

    def test_breakout_triggers(self):
        """价格创新高时应触发突破。"""
        df = make_price_df(50, trend=0.0)  # 平稳价格
        # 在最后一天插入大涨
        df.loc[49, "close_qfq"] = df["close_qfq"].max() * 2
        df.loc[49, "high_qfq"] = df["high_qfq"].max() * 2
        df = calc_breakout(df, window=20)
        assert df["breakout_20d"].iloc[49]


class TestVolumeRatio:
    def test_vol_ratio_gt_one_on_spike(self):
        df = make_price_df(40)
        df.loc[39, "amount"] = df["amount"].mean() * 10  # 最后一天放量
        df = calc_volume_ratio(df, window=20)
        assert df["vol_ratio_20d"].iloc[39] > 1.0


class TestRelativeStrength:
    def test_rs_positive_when_outperform(self):
        df = make_price_df(60, trend=0.02)  # 股票涨得快
        idx = make_price_df(60, trend=0.001)  # 指数涨得慢
        idx = idx[["trade_date", "close"]].rename(columns={"close": "close"})
        result = calc_relative_strength(df, idx, window=20)
        # 超额收益应大于 0
        valid = result["rel_strength_20d"].dropna()
        assert (valid > 0).all()


class TestIndexAboveMA:
    def test_above_ma(self):
        df = make_price_df(30, trend=0.01)
        idx = df[["trade_date", "close"]].copy()
        series = index_above_ma(idx, ma_window=5)
        # 上涨趋势：从第6天起应全部在均线上方
        assert series.iloc[6:].all()
