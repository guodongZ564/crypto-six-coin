"""CryptoQuant Pro collector：交易所净流（BTC/ETH）、供应盈亏（仅 BTC）。

CryptoQuant 完全不覆盖 SOL/UNI/LINK/LTC，且当前订阅套餐的 API 历史深度只有
约365天（更早日期直接返回空，不是报错）。这里按实际可拿到的做：BTC 有
exchange_netflow + supply_profit_pct + supply_pnl_ratio，ETH 只有
exchange_netflow。没配 CRYPTOQUANT_API_KEY 时直接抛错，交给调用方的
try/except 当作"这个源跳过"处理，不中断整轮采集。
"""

import os

import pandas as pd
import requests

API_BASE = "https://api.cryptoquant.com/v1"
SOURCE = "cryptoquant"


def _date_param(date_str: str) -> str:
    return date_str.replace("-", "")


def _get(path: str, params: dict, api_key: str) -> list:
    resp = requests.get(
        f"{API_BASE}{path}",
        params=params,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", {}).get("data", [])


def _require_api_key(api_key: str | None) -> str:
    api_key = api_key or os.environ.get("CRYPTOQUANT_API_KEY", "")
    if not api_key:
        raise RuntimeError("CRYPTOQUANT_API_KEY 未配置")
    return api_key


def collect_exchange_netflow(asset: str, cq_asset: str, start_date: str, end_date: str, api_key: str | None = None) -> pd.DataFrame:
    api_key = _require_api_key(api_key)

    params = {
        "exchange": "all_exchange",
        "window": "day",
        "from": _date_param(start_date),
        "to": _date_param(end_date),
        "limit": 100000,
    }
    data = _get(f"/{cq_asset}/exchange-flows/netflow", params, api_key)
    if not data:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(data)
    out = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "exchange_netflow",
        "value": df["netflow_total"].astype(float),
        "source": SOURCE,
    })
    return out[(out["date"] >= start_date) & (out["date"] <= end_date)].reset_index(drop=True)


def collect_supply_pnl(asset: str, cq_asset: str, start_date: str, end_date: str, api_key: str | None = None) -> pd.DataFrame:
    api_key = _require_api_key(api_key)

    params = {
        "window": "day",
        "from": _date_param(start_date),
        "to": _date_param(end_date),
        "limit": 100000,
    }
    data = _get(f"/{cq_asset}/network-indicator/pnl-supply", params, api_key)
    if not data:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    df = pd.DataFrame(data)
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
    if df.empty:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    pct_rows = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "supply_profit_pct",
        "value": df["profit_percent"].astype(float),
        "source": SOURCE,
    })

    loss = df["loss_amount"].astype(float)
    ratio = df["profit_amount"].astype(float) / loss.where(loss != 0)
    ratio_rows = pd.DataFrame({
        "date": df["date"],
        "asset": asset,
        "factor": "supply_pnl_ratio",
        "value": ratio,
        "source": SOURCE,
    })

    out = pd.concat([pct_rows, ratio_rows], ignore_index=True)
    return out.dropna(subset=["value"]).reset_index(drop=True)
