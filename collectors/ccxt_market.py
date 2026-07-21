"""ccxt 行情 collector：OHLCV 衍生技术因子 + 永续资金费率。

交易所固定用 OKX（config.exchange.ccxt_id / funding_ccxt_id）：Binance 对
GitHub Actions 默认 runner 所在的美国 IP 段有地域限制（451 Service
unavailable from a restricted location），OKX 的公开行情接口不受此限制。

backfill 和 daily 复用同一套函数：调用方只需传入想要落库的 [start_date, end_date]，
函数内部按需要的 lookback 缓冲多拉一段历史用于指标计算，最终只返回落在
[start_date, end_date] 区间内的行。

本版技术因子覆盖收盘价(close_price)/MA50/MA200/RSI14/MACD/布林带/量比；
close_price 是规格2打分层要用的（价格 vs MA/布林带都得拿它比较），派生指标
本身不含原始价格。200周线、月线 MACD、相对强度留到 collector 补全阶段一并
加入。

未平仓 OI、大户多空比走 OKX 公开统计接口（ccxt 没有统一封装这两个指标，直接
调 REST）。这两个接口本身历史就浅（约100天），跟规格里"仅约30天历史薄，
从现在起自记增量"的预期一致，不额外做分页拉取更早数据。
"""

from datetime import datetime, timedelta, timezone

import ccxt
import pandas as pd
import requests

OKX_STATS_BASE = "https://www.okx.com/api/v5/rubik/stat/contracts"

# 覆盖 MA200 等指标所需的最大回看窗口，多留一些余量
LOOKBACK_BUFFER_DAYS = 260


def _date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fetch_ohlcv_all(exchange: ccxt.Exchange, symbol: str, since_ms: int, until_ms: int) -> list:
    all_candles = []
    limit = 300  # OKX 现货K线（Candles/HistoryCandles）单次请求上限都是300，传更大的值会被 ccxt 静默截断
    empty_skip_ms = limit * 24 * 3600 * 1000  # 一个窗口的跨度

    cursor = since_ms
    while cursor <= until_ms:
        candles = exchange.fetch_ohlcv(symbol, timeframe="1d", since=cursor, limit=limit)
        if not candles:
            # 请求窗口早于交易所实际数据起点时 OKX 返回空页（不会截断到最早可用日期），
            # 往后跳一个窗口重试，而不是直接放弃——否则回填从很早的起点开始时会拿到 0 行
            cursor += empty_skip_ms
            continue

        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts <= cursor:
            break
        # 注意：OKX 一页返回的数量经常小于 limit，即使后面还有更多数据——不能拿
        # "返回数 < limit" 当作"到头了"的信号，只能靠 cursor 追上 until_ms 来判断结束
        cursor = last_ts + 1

    return [c for c in all_candles if since_ms <= c[0] <= until_ms]


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
    enriched["close_price"] = enriched["close"]
    enriched = enriched[(enriched["date"] >= start_date) & (enriched["date"] <= end_date)]

    factor_cols = ["close_price", "ma50", "ma200", "rsi14", "macd", "boll_upper", "boll_lower", "volume_ratio"]
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
    limit = 100
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


def collect_open_interest(asset: str, ccy: str, start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(f"{OKX_STATS_BASE}/open-interest-volume", params={"ccy": ccy, "period": "1D"}, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(data, columns=["ts", "oi_usd", "vol_usd"])
    # OKX 这两个统计接口的日线按 UTC+8（其所在地时区）零点分桶，不是 UTC 零点，
    # 直接按 UTC 取 .dt.date 会把每根 bar 错标成前一天，导致"今天"永远查不到数据
    df["date"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "open_interest",
        "value": df["oi_usd"].astype(float),
        "source": "okx_stats",
    })
    return out.sort_values("date").reset_index(drop=True)


def collect_long_short_ratio(asset: str, inst_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(
        f"{OKX_STATS_BASE}/long-short-account-ratio-contract", params={"instId": inst_id, "period": "1D"}, timeout=30
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(data, columns=["ts", "ratio"])
    # OKX 这两个统计接口的日线按 UTC+8（其所在地时区）零点分桶，不是 UTC 零点，
    # 直接按 UTC 取 .dt.date 会把每根 bar 错标成前一天，导致"今天"永远查不到数据
    df["date"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "long_short_ratio",
        "value": df["ratio"].astype(float),
        "source": "okx_stats",
    })
    return out.sort_values("date").reset_index(drop=True)
