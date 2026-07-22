"""动态分档的核心保证：某天的阈值只能用"严格早于当天"的历史算，不能被
当天或未来的分数影响——这是这个模块存在的唯一理由，必须专门测。
"""

import pandas as pd
import pytest

from backtest import dynamic_bands


def test_thresholds_before_min_history_are_none():
    dates = pd.date_range("2024-01-01", periods=10, freq="D").strftime("%Y-%m-%d")
    scores = {"BTC": pd.Series([0.5] * 10, index=dates)}
    result = dynamic_bands.compute_expanding_thresholds(scores, min_history=90)
    assert result["threshold_70"].isna().all()
    assert result["threshold_90"].isna().all()


def test_today_score_does_not_affect_todays_threshold():
    """当天阈值必须只用"截至昨天"的历史；把当天的分数改成极端值，
    今天的阈值不能变。"""
    dates = list(pd.date_range("2024-01-01", periods=95, freq="D").strftime("%Y-%m-%d"))
    baseline_scores = {"BTC": pd.Series([0.1] * 95, index=dates)}
    thresholds_baseline = dynamic_bands.compute_expanding_thresholds(baseline_scores, min_history=90)

    extreme_scores = {"BTC": pd.Series([0.1] * 94 + [999.0], index=dates)}
    thresholds_extreme = dynamic_bands.compute_expanding_thresholds(extreme_scores, min_history=90)

    last_date = dates[-1]
    assert thresholds_baseline.loc[last_date, "threshold_70"] == thresholds_extreme.loc[last_date, "threshold_70"]
    assert thresholds_baseline.loc[last_date, "threshold_90"] == thresholds_extreme.loc[last_date, "threshold_90"]


def test_pooling_across_assets():
    dates = list(pd.date_range("2024-01-01", periods=100, freq="D").strftime("%Y-%m-%d"))
    scores = {
        "BTC": pd.Series([0.1] * 100, index=dates),
        "ETH": pd.Series([0.9] * 100, index=dates),
    }
    result = dynamic_bands.compute_expanding_thresholds(scores, p_low=0.5, min_history=50)
    last_date = dates[-1]
    # 池化两个币的分数(0.1和0.9)，50分位应该落在两者之间，不是只看其中一个币
    assert 0.1 < result.loc[last_date, "threshold_70"] < 0.9


def test_classify_action_bands():
    assert dynamic_bands.classify_action(1.5, 0.5, 1.0) == "强烈看多 / 加仓"
    assert dynamic_bands.classify_action(0.7, 0.5, 1.0) == "看多 / 建仓"
    assert dynamic_bands.classify_action(0.2, 0.5, 1.0) == "中性 / 观望"
    assert dynamic_bands.classify_action(-0.7, 0.5, 1.0) == "看空 / 减仓"
    assert dynamic_bands.classify_action(-1.5, 0.5, 1.0) == "强烈看空 / 清仓"
    assert dynamic_bands.classify_action(0.7, None, None) == "中性 / 观望"


def test_apply_dynamic_bands_joins_and_reclassifies():
    dates = ["2024-01-01", "2024-01-02"]
    scores_df = pd.DataFrame({"composite_score": [1.5, -1.5]}, index=dates)
    thresholds = pd.DataFrame({"threshold_70": [0.5, 0.5], "threshold_90": [1.0, 1.0]}, index=dates)
    out = dynamic_bands.apply_dynamic_bands(scores_df, thresholds)
    assert out.loc["2024-01-01", "action"] == "强烈看多 / 加仓"
    assert out.loc["2024-01-02", "action"] == "强烈看空 / 清仓"
