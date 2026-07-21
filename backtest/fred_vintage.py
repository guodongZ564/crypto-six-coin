"""FRED point-in-time（ALFRED等价）宏观数据：拉全量修正历史，构造"某天实际
能看到的值"的时间线，供回测用。

跟 collectors/fred.py 的关系：fred.py 给线上 run_daily.py 用，永远拿"当前
最新修正值"（source=fred(revised)），这对当天决策没问题（当天能看到的本来
就是当前最新值）；但回测要重演历史某一天，不能用未来才会出现的修正值，所以
回测专用这个模块，独立抓取，不复用 fred.py。

原理：FRED 的 series/observations 接口把 realtime_start/realtime_end 设成
一个覆盖全部历史的宽区间时，会在一次请求里返回每个观测期(obs_date)在"每一段
被当作当前值的时间窗口(rt_start~rt_end)"里各自的取值——这就是完整的修正
历史，不用对每个历史日期单独发请求（实测验证过：M2SL 一次调用就拿到了
2015年前4个月、跨11年的全部132条修正记录）。
"""

import os

import pandas as pd
import requests

API_URL = "https://api.stlouisfed.org/fred/series/observations"
FAR_FUTURE = "9999-12-31"


def fetch_vintage_history(series_id: str, observation_start: str, observation_end: str, api_key: str | None = None) -> pd.DataFrame:
    """一次性拉全量修正历史，返回 obs_date|value|rt_start|rt_end 四列。"""
    api_key = api_key or os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise RuntimeError("FRED_API_KEY 未配置")

    rows = []
    offset = 0
    limit = 100000
    while True:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "observation_end": observation_end,
            "realtime_start": "1900-01-01",
            "realtime_end": FAR_FUTURE,
            "limit": limit,
            "offset": offset,
        }
        resp = requests.get(API_URL, params=params, timeout=60)
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        for o in observations:
            if o["value"] in (".", ""):
                continue
            rows.append({
                "obs_date": o["date"],
                "value": float(o["value"]),
                "rt_start": o["realtime_start"],
                "rt_end": o["realtime_end"],
            })
        if len(observations) < limit:
            break
        offset += limit

    df = pd.DataFrame(rows, columns=["obs_date", "value", "rt_start", "rt_end"])
    return df.sort_values(["obs_date", "rt_start"]).reset_index(drop=True)


def build_point_in_time_daily(vintage_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """把修正历史转成"asof_date(某天) -> 当时能看到的最新读数"的日频序列。

    两步查找，对每个 asof_date：
    1. 先定位"截至 asof_date，最新已经发布过的观测期"是哪个月（按该观测期
       第一次出现的 rt_start 判断"发布日"，不是它的 obs_date 本身）。
    2. 再在那个观测期自己的修正历史里，找 asof_date 落在哪一段
       (rt_start~rt_end)，取那一段的值——这样才是"asof_date 那天实际看到
       的数字"，不是若干年后的最终修正值。
    """
    if vintage_df.empty:
        return pd.DataFrame(columns=["date", "value"])

    first_release = (
        vintage_df.groupby("obs_date")["rt_start"].min()
        .reset_index()
        .sort_values("rt_start")
        .reset_index(drop=True)
    )
    first_release["rt_start_dt"] = pd.to_datetime(first_release["rt_start"])

    asof_index = pd.DataFrame({"date": pd.date_range(start_date, end_date, freq="D")})
    latest_obs = pd.merge_asof(
        asof_index.sort_values("date"),
        first_release[["obs_date", "rt_start_dt"]].sort_values("rt_start_dt"),
        left_on="date", right_on="rt_start_dt",
        direction="backward",
    ).dropna(subset=["obs_date"])
    latest_obs["date_str"] = latest_obs["date"].dt.strftime("%Y-%m-%d")

    vintage_df = vintage_df.copy()
    vintage_df["rt_start_dt"] = pd.to_datetime(vintage_df["rt_start"])

    rows = []
    for obs_date, group in latest_obs.groupby("obs_date"):
        candidates = vintage_df[vintage_df["obs_date"] == obs_date].sort_values("rt_start_dt")
        sub = pd.merge_asof(
            group[["date", "date_str"]].sort_values("date"),
            candidates[["rt_start_dt", "value"]].sort_values("rt_start_dt"),
            left_on="date", right_on="rt_start_dt",
            direction="backward",
        )
        rows.append(sub[["date_str", "value"]].rename(columns={"date_str": "date"}))

    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    return pd.concat(rows, ignore_index=True).dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def build_yoy_point_in_time_daily(vintage_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """跟 fred.py 里 units=pc1 的效果对应，但按 point-in-time 语义算：拿"某天
    known 的当期值"跟"同一天 known 的一年前那期值"比，不是拿两期的最终修正值比。
    """
    from datetime import datetime, timedelta

    buffered_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=380)).strftime("%Y-%m-%d")
    daily = build_point_in_time_daily(vintage_df, buffered_start, end_date)
    if daily.empty:
        return pd.DataFrame(columns=["date", "value"])

    value_by_date = dict(zip(daily["date"], daily["value"]))
    rows = []
    for _, row in daily.iterrows():
        d = row["date"]
        if d < start_date:
            continue
        prior_date = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        prior_value = value_by_date.get(prior_date)
        if not prior_value:
            continue
        rows.append({"date": d, "value": (row["value"] / prior_value - 1) * 100})

    return pd.DataFrame(rows, columns=["date", "value"])
