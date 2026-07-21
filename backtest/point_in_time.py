"""构造某个回测日 t "实际能看到"的历史切片，供逐日重算合成分用。

跟规格2线上跑 run_daily.py 时不一样，这里额外处理两类"意外偷看未来"的坑，
线上daily不用管（当天数据发布到哪就是哪，天然point-in-time），但回测重演
历史时必须管：

1. 数据发布延迟：CryptoQuant 有些指标实测比"date"标注的当天晚发布（规格1/2
   阶段测过：ETH净流、BTC供应盈亏经常晚1天），回测不能只按 date<=t 过滤，
   要按"实际可得时间"卡住，宁可少用一天数据也不偷看未来。
2. 宏观 vintage：fed_funds_rate/m2 用 ALFRED point-in-time 缓存
   (data/alfred_vintage_macro.parquet，由 backtest/build_vintage_cache.py
   预先拉好)替换掉 factor_timeseries.parquet 里的 FRED 终值版本；
   treasury_10y 因为是日频市场数据、实测从未被修正过，直接用常规采集的值
   （见 backtest/build_vintage_cache.py 里的说明，这是记录在案的简化）。
"""

from pathlib import Path

import pandas as pd

VINTAGE_CACHE_PATH = "data/alfred_vintage_macro.parquet"

# 按 source 标记的发布延迟天数
SOURCE_LAG_DAYS = {
    "cryptoquant": 1,
}

VINTAGE_REPLACED_FACTORS = {"fed_funds_rate", "m2"}


def load_vintage_cache(path: str = VINTAGE_CACHE_PATH) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])
    return pd.read_parquet(p)


def build_point_in_time_history(full_history: pd.DataFrame, vintage_cache: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """返回"截至 target_date 这天，实际能看到"的完整长表切片。"""
    hist = full_history[full_history["date"] <= target_date]

    hist = hist[~hist["factor"].isin(VINTAGE_REPLACED_FACTORS)]
    if not vintage_cache.empty:
        vintage_slice = vintage_cache[
            (vintage_cache["date"] <= target_date) & (vintage_cache["factor"].isin(VINTAGE_REPLACED_FACTORS))
        ]
        hist = pd.concat([hist, vintage_slice], ignore_index=True)

    for source, lag in SOURCE_LAG_DAYS.items():
        cutoff = (pd.Timestamp(target_date) - pd.Timedelta(days=lag)).strftime("%Y-%m-%d")
        drop_mask = (hist["source"] == source) & (hist["date"] > cutoff)
        hist = hist[~drop_mask]

    return hist.reset_index(drop=True)
