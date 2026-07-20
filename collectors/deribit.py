"""Deribit DVOL 波动率指数 collector（BTC/ETH，2021年3月上线至今）。

Deribit 单次请求最多返回 1000 根日线，用响应里的 continuation 时间戳往回翻页：
continuation 是"已拿到数据"的更早边界，下一页请求把 end_timestamp 设成它即可，
continuation 为 None（或不再前移）说明拿到头了。
"""

from datetime import datetime, timezone

import pandas as pd
import requests

API_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
SOURCE = "deribit"
DAY_MS = 24 * 3600 * 1000
RESOLUTION = "86400"  # 日线


def _date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fetch_all(currency: str, start_ms: int, end_ms: int) -> list:
    all_candles = []
    cursor_end = end_ms
    while True:
        params = {
            "currency": currency,
            "start_timestamp": start_ms,
            "end_timestamp": cursor_end,
            "resolution": RESOLUTION,
        }
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        result = resp.json().get("result", {})
        data = result.get("data", [])
        if not data:
            break
        all_candles.extend(data)

        continuation = result.get("continuation")
        if continuation is None or continuation >= cursor_end:
            break
        cursor_end = continuation

    return all_candles


def collect_dvol(asset: str, currency: str, start_date: str, end_date: str) -> pd.DataFrame:
    start_ms = _date_to_ms(start_date)
    end_ms = _date_to_ms(end_date) + DAY_MS - 1

    candles = _fetch_all(currency, start_ms, end_ms)
    if not candles:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "dvol",
        "value": df["close"].astype(float),
        "source": SOURCE,
    })
    return out.sort_values("date").reset_index(drop=True)
