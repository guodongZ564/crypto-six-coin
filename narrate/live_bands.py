"""动态分档在线上的版本：每天从 data/composite_score_history.parquet 里取
BTC/ETH/SOL 截至昨天(不含今天)的合成分历史，池化算70/90分位，作为今天的
分档边界。跟 backtest/dynamic_bands.py 的口径完全一致（同一套70/90分位、
BTC/ETH/SOL池化、严格早于当天），只是这版不用像回测那样逐日算一整条阈值
序列——线上每天只需要"今天"这一个阈值，从已经累积的历史里查一次就够，
不用重新跑一遍多年历史的评分。

历史不够（<MIN_HISTORY天）时返回 (None, None)，调用方按"这天判不了强弱
看多/看空档，退回中性"处理，不是硬凑一个不可靠的阈值。
"""

from pathlib import Path

import numpy as np
import pandas as pd

HISTORY_PATH = "data/composite_score_history.parquet"
LIVE_ASSETS = ["BTC", "ETH", "SOL"]
P_LOW = 0.7
P_HIGH = 0.9
MIN_HISTORY = 90


def load_history(path: str = HISTORY_PATH) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["date", "asset", "composite_score"])
    return pd.read_parquet(p)


def compute_today_thresholds(history: pd.DataFrame, today: str) -> tuple:
    prior = history[(history["date"] < today) & (history["asset"].isin(LIVE_ASSETS))]
    prior = prior.dropna(subset=["composite_score"])
    if len(prior) < MIN_HISTORY:
        return None, None
    abs_scores = prior["composite_score"].abs().to_numpy()
    t70 = float(np.percentile(abs_scores, P_LOW * 100))
    t90 = float(np.percentile(abs_scores, P_HIGH * 100))
    return t70, t90


def append_today(history: pd.DataFrame, today: str, scores_by_asset: dict) -> pd.DataFrame:
    """scores_by_asset: {asset: composite_score}。追加今天的真实值，按(date,asset)去重keep=last。"""
    rows = [{"date": today, "asset": a, "composite_score": s} for a, s in scores_by_asset.items() if s is not None]
    new_df = pd.DataFrame(rows, columns=["date", "asset", "composite_score"])
    combined = pd.concat([history, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "asset"], keep="last")
    return combined.sort_values(["date", "asset"]).reset_index(drop=True)


def save_history(history: pd.DataFrame, path: str = HISTORY_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    history.to_parquet(path, index=False)
