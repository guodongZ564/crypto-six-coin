"""FRED 宏观因子 collector（核心CPI/核心PCE/M2/联邦基金利率/10Y美债）。

FRED 默认返回的是修正后终值（不是 ALFRED 初次发布值），本版直接落地终值供
线上使用，source 标记为 "fred(revised)"，规格3 如需回测防未来函数，再改接
ALFRED 拿初次发布值。

宏观数据按月/按发布节奏更新，不是每个自然日都有观测值，因此本 collector
按 asOf 语义处理：抓取序列全部历史（不按 start_date 过滤请求，只用
end_date 限定右边界)，前向填充到自然日频率，最后再按 [start_date, end_date]
切片返回。这样 backfill 和 daily 才能复用同一个函数签名——daily 传入
start_date=end_date=今天，拿到的是"截至今天的最新已知值"，而不是要求今天
恰好是发布日。
"""

import os

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"
SOURCE = "fred(revised)"


def _fetch_raw_series(series_id: str, units: str, end_date: str, api_key: str) -> pd.DataFrame:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_end": end_date,
        "units": units,
    }
    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    observations = resp.json().get("observations", [])

    rows = [
        {"date": o["date"], "value": float(o["value"])}
        for o in observations
        if o["value"] not in (".", "")
    ]
    return pd.DataFrame(rows, columns=["date", "value"])


def _forward_fill_daily(raw: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if raw.empty:
        return raw

    idx = pd.date_range(raw["date"].min(), end_date, freq="D")
    filled = raw.set_index(pd.to_datetime(raw["date"]))["value"].reindex(idx).ffill()

    out = filled.rename_axis("date").reset_index()
    out["date"] = out["date"].dt.date.astype(str)
    out = out[(out["date"] >= start_date) & (out["date"] <= end_date)]
    return out.dropna(subset=["value"]).reset_index(drop=True)


def collect_macro_factors(start_date: str, end_date: str, series_config: dict, api_key: str | None = None) -> pd.DataFrame:
    api_key = api_key or os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise RuntimeError("FRED_API_KEY 未配置")

    frames = []
    for factor, spec in series_config.items():
        raw = _fetch_raw_series(spec["id"], spec.get("units", "lin"), end_date, api_key)
        daily = _forward_fill_daily(raw, start_date, end_date)
        if daily.empty:
            continue
        daily["asset"] = "MACRO"
        daily["factor"] = factor
        daily["source"] = SOURCE
        frames.append(daily[["date", "asset", "factor", "value", "source"]])

    if not frames:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    return pd.concat(frames, ignore_index=True)
