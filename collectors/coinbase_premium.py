"""Coinbase 溢价 collector：自算 Coinbase 现货价 vs 参照交易所价格的百分比溢价。

规格原文是"Coinbase vs Binance"，但 Binance 对 GitHub Actions 的美国 IP 段有
地域限制（同 ccxt_market.py 里的问题），这里换成已经验证可用的 OKX 做参照价。

只做 BTC——Coinbase Premium Index 惯例上就是 BTC/USD 溢价，不是通用的多币种指标。
Coinbase 公开 K 线接口单次请求最多 300 根，按 300 天一批分页拉取。
"""

from datetime import datetime, timedelta

import ccxt
import pandas as pd
import requests

from collectors.ccxt_market import _date_to_ms, _fetch_ohlcv_all

COINBASE_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
SOURCE = "coinbase_premium"
MAX_DAYS_PER_REQUEST = 300


def _fetch_coinbase_daily_close(product_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_rows = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=MAX_DAYS_PER_REQUEST - 1), end)
        params = {
            "granularity": 86400,
            "start": cursor.strftime("%Y-%m-%d"),
            "end": chunk_end.strftime("%Y-%m-%d"),
        }
        resp = requests.get(
            COINBASE_URL.format(product_id=product_id),
            params=params,
            headers={"User-Agent": "six-coin-factor-bot"},
            timeout=30,
        )
        resp.raise_for_status()
        all_rows.extend(resp.json())
        cursor = chunk_end + timedelta(days=1)

    if not all_rows:
        return pd.DataFrame(columns=["date", "close"])

    df = pd.DataFrame(all_rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")
    return df[["date", "close"]]


def _fetch_ref_daily_close(exchange, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    since_ms = _date_to_ms(start_date)
    until_ms = _date_to_ms(end_date) + 24 * 3600 * 1000 - 1

    candles = _fetch_ohlcv_all(exchange, symbol, since_ms, until_ms)
    if not candles:
        return pd.DataFrame(columns=["date", "close"])

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")
    return df[["date", "close"]]


def collect_premium(asset: str, coinbase_product: str, ref_symbol: str, start_date: str, end_date: str, ref_exchange=None) -> pd.DataFrame:
    ref_exchange = ref_exchange or ccxt.okx({"enableRateLimit": True})

    cb = _fetch_coinbase_daily_close(coinbase_product, start_date, end_date)
    if cb.empty:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    ref = _fetch_ref_daily_close(ref_exchange, ref_symbol, start_date, end_date).rename(columns={"close": "ref_close"})

    merged = cb.merge(ref, on="date", how="inner")
    merged = merged[(merged["date"] >= start_date) & (merged["date"] <= end_date)]
    if merged.empty:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    cb_close = merged["close"].astype(float)
    ref_close = merged["ref_close"].astype(float)
    premium_pct = (cb_close - ref_close) / ref_close * 100

    out = pd.DataFrame({
        "date": merged["date"],
        "asset": asset,
        "factor": "coinbase_premium",
        "value": premium_pct,
        "source": SOURCE,
    })
    return out.sort_values("date").reset_index(drop=True)
