"""Parquet 时间序列存取：长格式 date|asset|factor|value|source。

更新策略固定为「读全量 → concat → 按 (date,asset,factor) 去重 keep=last → 整体写回」，
不做追加式写入。回填数据量大时，调用方（backfill.py）按 collector/资产分批调用
upsert，从而把单次读写的数据量控制在合理范围内。

upsert_scores 是给 data/scores_timeseries.parquet 用的宽表版本（一行=一天一币的
评分快照，列是各维度分/合成分/动作档等，不是长表），去重 key 是 (date,asset)。
"""

from pathlib import Path

import pandas as pd

SCHEMA_COLUMNS = ["date", "asset", "factor", "value", "source"]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SCHEMA_COLUMNS)


def _coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return _empty_frame()
    df = df[SCHEMA_COLUMNS].copy()
    df["date"] = df["date"].astype(str)
    df["asset"] = df["asset"].astype(str)
    df["factor"] = df["factor"].astype(str)
    df["value"] = df["value"].astype(float)
    df["source"] = df["source"].astype(str)
    return df


def load(path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return _empty_frame()
    return pd.read_parquet(path)


def upsert(path, new_df: pd.DataFrame) -> pd.DataFrame:
    """把 new_df 合入 path 指向的 parquet，返回合并后的全量 DataFrame。"""
    path = Path(path)
    new_df = _coerce_schema(new_df)
    existing = load(path)

    combined = pd.concat([existing, new_df], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["date", "asset", "factor"], keep="last")
        combined = combined.sort_values(["date", "asset", "factor"]).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined


def upsert_scores(path, new_df: pd.DataFrame, key_columns=("date", "asset")) -> pd.DataFrame:
    """宽表版 upsert：读全量 → concat → 按 key_columns 去重 keep=last → 整体写回。"""
    path = Path(path)
    key_columns = list(key_columns)

    if path.exists():
        existing = pd.read_parquet(path)
    else:
        existing = pd.DataFrame(columns=new_df.columns)

    combined = pd.concat([existing, new_df], ignore_index=True)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=key_columns, keep="last")
        combined = combined.sort_values(key_columns).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined
