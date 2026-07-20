"""ccxt 行情 collector：OHLCV 衍生技术因子 + 永续资金费率。

交易所固定用 OKX（config.exchange.ccxt_id / funding_ccxt_id）：Binance 对
GitHub Actions 默认 runner 所在的美国 IP 段有地域限制（451 Service
unavailable from a restricted location），OKX 的公开行情接口不受此限制。

backfill 和 daily 复用同一套函数：调用方只需传入想要落库的 [start_date, end_date]，
函数内部按需要的 lookback 缓冲多拉一段历史用于指标计算，最终只返回落在
[start_date, end_date] 区间内的行。

本版技术因子先覆盖 MA50/MA200/RSI14/MACD/布林带/量比；200周线、月线 MACD、
相对强度留到 collector 补全阶段一并加入。
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd

# 覆盖 MA200 等指标所需的最大回看窗口，多留一些余量
LOOKBACK_BUFFER_DAYS = 260


def _date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fetch_ohlcv_all(exchange: ccxt.Exchange, symbol: str, since_ms: int, until_ms: int) -> list:
    all_candles = []
    limit = 1000
    while since_ms <= until_ms:
        candles = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=limit)
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts <= since_ms:
            break
        since_ms = last_ts + 1
        if len(candles) < limit:
            break
    return [c for c in all_candles if c[0] <= until_ms]


def _compute_technical_factors(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv_df.sort_values("date").reset_index(drop=True)

    df["ma50"] = df["close"].rolling(50).mean()
    df["ma200"] = df["close"].rolling(200).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi14"] = 100 - (100 / (1 + rs))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26

    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    df["boll_upper"] = mid + 2 * std
    df["boll_lower"] = mid - 2 * std

    df["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()

    return df


def collect_ohlcv_factors(asset: str, symbol: str, start_date: str, end_date: str, exchange=None) -> pd.DataFrame:
    exchange = exchange or ccxt.okx({"enableRateLimit": True})

    fetch_start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=LOOKBACK_BUFFER_DAYS)
    since_ms = _date_to_ms(fetch_start.strftime("%Y-%m-%d"))
    until_ms = _date_to_ms(end_date) + 24 * 3600 * 1000 - 1

    candles = _fetch_ohlcv_all(exchange, symbol, since_ms, until_ms)
    if not candles:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    raw = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    raw["date"] = pd.to_datetime(raw["ts"], unit="ms", utc=True).dt.date.astype(str)
    raw = raw.drop_duplicates(subset="date", keep="last")

    enriched = _compute_technical_factors(raw)
    enriched = enriched[(enriched["date"] >= start_date) & (enriched["date"] <= end_date)]

    factor_cols = ["ma50", "ma200", "rsi14", "macd", "boll_upper", "boll_lower", "volume_ratio"]
    long_rows = enriched.melt(id_vars=["date"], value_vars=factor_cols, var_name="factor", value_name="value")
    long_rows = long_rows.dropna(subset=["value"])
    long_rows["asset"] = asset
    long_rows["source"] = f"ccxt:{exchange.id}"

    return long_rows[["date", "asset", "factor", "value", "source"]].reset_index(drop=True)


def collect_funding_rate(asset: str, symbol: str, start_date: str, end_date: str, exchange=None) -> pd.DataFrame:
    exchange = exchange or ccxt.okx({"enableRateLimit": True})

    since_ms = _date_to_ms(start_date)
    until_ms = _date_to_ms(end_date) + 24 * 3600 * 1000 - 1

    all_rates = []
    limit = 1000
    cursor = since_ms
    while cursor <= until_ms:
        batch = exchange.fetch_funding_rate_history(symbol, since=cursor, limit=limit)
        if not batch:
            break
        all_rates.extend(batch)
        last_ts = batch[-1]["timestamp"]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        if len(batch) < limit:
            break

    if not all_rates:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(all_rates)
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.date.astype(str)
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
    # 一天内可能有多次结算（每8小时），落库取当日最后一次结算值
    df = df.sort_values("timestamp").drop_duplicates(subset="date", keep="last")

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "funding_rate",
        "value": df["fundingRate"].astype(float),
        "source": f"ccxt:{exchange.id}",
    })
    return out.reset_index(drop=True)
