"""DefiLlama collector：链 TVL（ETH/SOL）、稳定币总市值、Uniswap DEX 量、Uniswap 协议费用。

各接口口径历史上可能改过定义（比如 TVL 统计范围调整），本版只按 collector
的实际起始日落库，不做跨口径断点处理——那是规格3 的事，这里只记录数据。
"""

import pandas as pd
import requests

SOURCE = "defillama"

CHAIN_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
DEX_SUMMARY_URL = "https://api.llama.fi/summary/dexs/{protocol}"
FEES_SUMMARY_URL = "https://api.llama.fi/summary/fees/{protocol}"


def _filter_range(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)].reset_index(drop=True)


def collect_chain_tvl(asset: str, chain: str, start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(CHAIN_TVL_URL.format(chain=chain), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"], unit="s", utc=True).dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "chain_tvl",
        "value": df["tvl"].astype(float),
        "source": SOURCE,
    })
    return _filter_range(out, start_date, end_date)


def collect_stablecoin_mcap(start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(STABLECOIN_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data:
        usd = item.get("totalCirculatingUSD", {}).get("peggedUSD")
        if usd is None:
            continue
        date = pd.to_datetime(int(item["date"]), unit="s", utc=True).date().isoformat()
        rows.append({"date": date, "value": float(usd)})

    if not rows:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(rows).drop_duplicates(subset="date", keep="last")
    out = pd.DataFrame({
        "date": df["date"],
        "asset": "MARKET",
        "factor": "stablecoin_mcap",
        "value": df["value"],
        "source": SOURCE,
    })
    return _filter_range(out, start_date, end_date)


def _collect_summary_chart(url: str, factor_name: str, asset: str, start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(
        url,
        params={"excludeTotalDataChart": "false", "excludeTotalDataChartBreakdown": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    chart = resp.json().get("totalDataChart", [])
    if not chart:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(chart, columns=["ts", "value"])
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.date.astype(str)
    df = df.drop_duplicates(subset="date", keep="last")

    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": factor_name,
        "value": df["value"].astype(float),
        "source": SOURCE,
    })
    return _filter_range(out, start_date, end_date)


def collect_dex_volume(asset: str, protocol: str, start_date: str, end_date: str) -> pd.DataFrame:
    return _collect_summary_chart(DEX_SUMMARY_URL.format(protocol=protocol), "dex_volume", asset, start_date, end_date)


def collect_protocol_fees(asset: str, protocol: str, start_date: str, end_date: str) -> pd.DataFrame:
    return _collect_summary_chart(FEES_SUMMARY_URL.format(protocol=protocol), "protocol_fees", asset, start_date, end_date)
