"""三类归一化(绝对阈值/趋势/分位)的通用helper测试，加反指因子方向专项测试。

反指因子最容易在写代码时凭直觉搞反方向（比如以为"数值越高分越高"），所以每
个反指因子都单独断言一个极端输入，确认输出方向没被写反。
"""

import pandas as pd
import pytest

from core.normalize import (
    NormalizeContext,
    percentile_rank,
    score_by_thresholds,
    score_by_trend,
    score_btc_loss_supply_ratio,
    score_dvol,
    score_fear_greed,
    score_funding_rate,
    score_long_short_ratio,
)


def _make_history(rows):
    return pd.DataFrame(rows, columns=["date", "asset", "factor", "value", "source"])


# ---------- 绝对阈值型 ----------

def test_score_by_thresholds_absolute():
    breakpoints = [(20, 2.0), (40, 1.0), (60, 0.0), (80, -1.0), (None, -2.0)]
    assert score_by_thresholds(10, breakpoints) == 2.0
    assert score_by_thresholds(50, breakpoints) == 0.0
    assert score_by_thresholds(90, breakpoints) == -2.0


# ---------- 趋势型 ----------

def test_score_by_trend_rising_falling_flat():
    rising_baseline = pd.Series([100, 101, 102, 103, 104, 105, 106])
    assert score_by_trend(120, rising_baseline, window=7, up_score=1, flat_score=0, down_score=-1) == 1

    flat_baseline = pd.Series([100] * 7)
    assert score_by_trend(80, flat_baseline, window=7, up_score=1, flat_score=0, down_score=-1) == -1
    assert score_by_trend(100.5, flat_baseline, window=7, up_score=1, flat_score=0, down_score=-1, flat_band_pct=0.02) == 0


def test_score_by_trend_empty_history_returns_none():
    assert score_by_trend(100, pd.Series(dtype=float)) is None


# ---------- 分位型 ----------

def test_percentile_rank_insufficient_history_returns_none():
    short_hist = pd.Series(range(10))
    assert percentile_rank(5, short_hist, min_history=30) is None


def test_percentile_rank_basic():
    hist = pd.Series(range(100))
    assert percentile_rank(95, hist, min_history=30) == pytest.approx(0.95, abs=0.02)
    assert percentile_rank(5, hist, min_history=30) == pytest.approx(0.05, abs=0.02)


# ---------- 反指因子方向测试 ----------

def test_fear_greed_reverse_direction():
    extreme_fear = _make_history([("2026-01-01", "MARKET", "fear_greed", 15, "test")])
    ctx = NormalizeContext(history=extreme_fear, asset="MARKET", target_date="2026-01-01")
    assert score_fear_greed(ctx) == 2.0  # 极度恐慌(低值)必须是正分

    extreme_greed = _make_history([("2026-01-01", "MARKET", "fear_greed", 90, "test")])
    ctx2 = NormalizeContext(history=extreme_greed, asset="MARKET", target_date="2026-01-01")
    assert score_fear_greed(ctx2) == -2.0  # 极度贪婪(高值)必须是负分


def test_funding_rate_reverse_direction():
    extreme_negative = _make_history([("2026-01-01", "BTC", "funding_rate", -0.001, "test")])
    ctx = NormalizeContext(history=extreme_negative, asset="BTC", target_date="2026-01-01")
    assert score_funding_rate(ctx) == 2.0  # 极负费率(空头付多头)必须是正分

    extreme_positive = _make_history([("2026-01-01", "BTC", "funding_rate", 0.001, "test")])
    ctx2 = NormalizeContext(history=extreme_positive, asset="BTC", target_date="2026-01-01")
    assert score_funding_rate(ctx2) == -2.0  # 极正费率(过热)必须是负分


def test_long_short_ratio_reverse_direction():
    dates = list(pd.date_range("2026-01-01", periods=35, freq="D").strftime("%Y-%m-%d"))
    rows = [(d, "BTC", "long_short_ratio", 1.0 + i * 0.01, "test") for i, d in enumerate(dates[:-1])]
    rows.append((dates[-1], "BTC", "long_short_ratio", 5.0, "test"))  # 当日历史高位(极度看多)
    history = _make_history(rows)
    ctx = NormalizeContext(history=history, asset="BTC", target_date=dates[-1])
    assert score_long_short_ratio(ctx) == -1.0  # 极度看多是反指看空，必须是负分


def test_dvol_reverse_direction():
    dates = list(pd.date_range("2026-01-01", periods=35, freq="D").strftime("%Y-%m-%d"))
    rows = [(d, "BTC", "dvol", 40 + i, "test") for i, d in enumerate(dates[:-1])]
    rows.append((dates[-1], "BTC", "dvol", 200, "test"))  # 当日历史高位(极端波动/恐慌)
    history = _make_history(rows)
    ctx = NormalizeContext(history=history, asset="BTC", target_date=dates[-1])
    assert score_dvol(ctx) == 1.0  # DVOL 极高是反指看多，必须是正分


def test_btc_loss_supply_ratio_reverse_direction():
    history = _make_history([("2026-01-01", "BTC", "supply_profit_pct", 30, "test")])  # profit=30% -> loss=70%
    ctx = NormalizeContext(history=history, asset="BTC", target_date="2026-01-01")
    assert score_btc_loss_supply_ratio(ctx) == 2.0  # 亏损供应比越高(近底部)必须是正分
