"""Alternative.me 恐慌贪婪指数 collector（2018 年至今，一次性全量接口）。"""

import pandas as pd
import requests

SOURCE = "alternative.me"
API_URL = "https://api.alternative.me/fng/"


def collect_fear_greed(start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(API_URL, params={"limit": 0, "format": "json"}, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    rows = []
    for item in data:
        date = pd.to_datetime(int(item["timestamp"]), unit="s", utc=True).date().isoformat()
        if start_date <= date <= end_date:
            rows.append({
                "date": date,
                "asset": "MARKET",
                "factor": "fear_greed",
                "value": float(item["value"]),
                "source": SOURCE,
            })

    return pd.DataFrame(rows, columns=["date", "asset", "factor", "value", "source"])
