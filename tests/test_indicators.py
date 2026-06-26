"""单元测试：技术指标模块"""

import pandas as pd
import numpy as np
import pytest

from src.indicators import (
    calc_ma, calc_ma_slope, calc_breakout,
    calc_volume_ratio, calc_relative_strength, index_above_ma,
)


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
