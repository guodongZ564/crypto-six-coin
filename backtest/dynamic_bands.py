"""动态分档：用 BTC/ETH/SOL 合成分的滚动历史分位数重定分档边界，替代固定的
±0.4/±1.0（规格3第一版回测发现"强烈看多/强烈看空"几乎从没触发过，固定阈值
偏离了合成分实际能达到的分布范围）。

只用"严格早于当天"的历史算当天的分位阈值——这跟项目里其他趋势/分位类因子
统一的防未来函数口径一致：今天的分档边界不能被今天自己的分数影响，更不能
用回测样本里"未来"的分数去定"过去"某天的分档。三币（BTC/ETH/SOL）的合成分
绝对值池化在一起算分位，不是各币各算一套——用户的原话是"大币合成分的历史
分位"，理解成一个共享的分布。

这套动态分档只在回测/校准场景用，不改 core/score.py 里线上 run_scoring.py
用的固定分档表——固定表要不要换成动态版，是这轮实验有结论之后再决定的事。
"""

import numpy as np
import pandas as pd


def compute_expanding_thresholds(scores_by_asset: dict, p_low: float = 0.7, p_high: float = 0.9, min_history: int = 90) -> pd.DataFrame:
    """scores_by_asset: {asset: pd.Series(index=date字符串, values=composite_score)}。
    返回按 date 排序索引的 DataFrame(threshold_70, threshold_90)，min_history
    天之前阈值是 NaN（历史不足，不分档，等价于回退成"中性"处理）。
    """
    pooled = []
    for asset, s in scores_by_asset.items():
        df = s.dropna().rename("score").reset_index()
        df.columns = ["date", "score"]
        pooled.append(df)
    pooled_df = pd.concat(pooled, ignore_index=True)
    pooled_df["abs_score"] = pooled_df["score"].abs()

    by_date = pooled_df.groupby("date")["abs_score"].apply(list).sort_index()

    rows = []
    history = []
    for d, today_vals in by_date.items():
        if len(history) >= min_history:
            arr = np.array(history)
            t70 = float(np.percentile(arr, p_low * 100))
            t90 = float(np.percentile(arr, p_high * 100))
        else:
            t70, t90 = None, None
        rows.append({"date": d, "threshold_70": t70, "threshold_90": t90})
        history.extend(today_vals)

    return pd.DataFrame(rows).set_index("date")


def classify_action(score: float | None, threshold_70: float | None, threshold_90: float | None) -> str:
    if score is None or threshold_70 is None or threshold_90 is None:
        return "中性 / 观望"
    if score >= threshold_90:
        return "强烈看多 / 加仓"
    if score >= threshold_70:
        return "看多 / 建仓"
    if score <= -threshold_90:
        return "强烈看空 / 清仓"
    if score <= -threshold_70:
        return "看空 / 减仓"
    return "中性 / 观望"


def apply_dynamic_bands(scores_df: pd.DataFrame, thresholds: pd.DataFrame) -> pd.DataFrame:
    """给 scores_df(index=date, 含 composite_score 列) 加两列
    (threshold_70/threshold_90) 并重算 action 列，返回新 DataFrame（不改原对象）。"""
    out = scores_df.join(thresholds, how="left")
    out["action"] = [
        classify_action(row.composite_score, row.threshold_70, row.threshold_90)
        for row in out.itertuples()
    ]
    return out
