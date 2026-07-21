"""IC/单调性/策略绩效指标的单测，用构造出来的、已知答案的合成数据验证公式，
不依赖真实回测跑出来的数据（那些留给 backtest 的输出去人工审）。
"""

import numpy as np
import pandas as pd
import pytest

from backtest import metrics


def test_forward_return_basic():
    close = pd.Series([100, 110, 121, 133.1], index=["d1", "d2", "d3", "d4"])
    fwd = metrics.forward_return(close, 1)
    assert fwd["d1"] == pytest.approx(0.10, abs=1e-6)
    assert fwd["d2"] == pytest.approx(0.10, abs=1e-6)
    assert pd.isna(fwd["d4"])  # 最后一天没有"未来"数据


def test_rank_ic_perfect_positive_correlation():
    dates = [f"d{i}" for i in range(30)]
    scores = pd.Series(range(30), index=dates, dtype=float)
    returns = pd.Series(range(30), index=dates, dtype=float)  # 完全同向
    result = metrics.rank_ic(scores, returns)
    assert result["ic"] == pytest.approx(1.0, abs=1e-6)
    assert result["n"] == 30


def test_rank_ic_perfect_negative_correlation():
    dates = [f"d{i}" for i in range(30)]
    scores = pd.Series(range(30), index=dates, dtype=float)
    returns = pd.Series(range(29, -1, -1), index=dates, dtype=float)  # 完全反向
    result = metrics.rank_ic(scores, returns)
    assert result["ic"] == pytest.approx(-1.0, abs=1e-6)


def test_rank_ic_insufficient_samples_returns_none():
    scores = pd.Series([1, 2, 3], index=["d1", "d2", "d3"], dtype=float)
    returns = pd.Series([1, 2, 3], index=["d1", "d2", "d3"], dtype=float)
    result = metrics.rank_ic(scores, returns)
    assert result["ic"] is None


def test_is_monotonic_decreasing():
    assert metrics.is_monotonic_decreasing(pd.Series([0.05, 0.03, 0.0, -0.02, -0.05]))
    assert not metrics.is_monotonic_decreasing(pd.Series([0.05, 0.06, 0.0, -0.02, -0.05]))


def test_strategy_performance_flat_zero_return():
    daily_returns = pd.Series([0.0] * 10, index=[f"d{i}" for i in range(10)])
    positions = pd.Series([0.0] * 10, index=[f"d{i}" for i in range(10)])
    perf = metrics.strategy_performance(daily_returns, positions)
    assert perf["annualized_return"] == pytest.approx(0.0, abs=1e-9)
    assert perf["trade_count"] == 0
    assert perf["avg_holding_days"] is None


def test_strategy_performance_single_holding_episode():
    dates = [f"d{i}" for i in range(6)]
    positions = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0, 0.0], index=dates)
    daily_returns = pd.Series([0.0, 0.01, 0.01, 0.01, 0.0, 0.0], index=dates)
    perf = metrics.strategy_performance(daily_returns, positions)
    assert perf["trade_count"] == 2  # 0->1 进场一次，1->0 出场一次
    assert perf["avg_holding_days"] == pytest.approx(3.0, abs=1e-6)
