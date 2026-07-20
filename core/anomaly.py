"""滚动 z-score 异动检测。

防未来函数：对 target_date 的异动判断，统计窗口严格取 target_date 之前
（不含当天）最近 window_days 天的历史。窗口不足 min_window_days 时标记为
"历史不足"，不参与阈值判断。
"""

import numpy as np
import pandas as pd


def compute_z_scores(history: pd.DataFrame, target_date: str, config: dict) -> list[dict]:
    window_days = config.get("window_days", 90)
    min_window_days = config.get("min_window_days", 30)

    results = []
    if history.empty:
        return results

    for (asset, factor), group in history.groupby(["asset", "factor"]):
        group = group.sort_values("date")
        today_rows = group[group["date"] == target_date]
        if today_rows.empty:
            continue
        today_value = float(today_rows["value"].iloc[-1])

        window = group[group["date"] < target_date].tail(window_days)
        if len(window) < min_window_days:
            results.append({
                "asset": asset,
                "factor": factor,
                "value": today_value,
                "mean": None,
                "std": None,
                "z": None,
                "status": "insufficient_history",
            })
            continue

        mu = float(window["value"].mean())
        sigma = float(window["value"].std(ddof=0))
        z = 0.0 if sigma == 0 or np.isnan(sigma) else (today_value - mu) / sigma

        results.append({
            "asset": asset,
            "factor": factor,
            "value": today_value,
            "mean": mu,
            "std": sigma,
            "z": z,
            "status": "ok",
        })

    return results


def flag_anomalies(results: list[dict], config: dict, factor_meta: dict) -> list[dict]:
    z_threshold = config.get("z_threshold", 2.0)
    hard_thresholds = config.get("hard_thresholds", {})

    flagged = []
    for r in results:
        if r["status"] != "ok":
            continue

        factor = r["factor"]
        reasons = []

        if r["z"] is not None and abs(r["z"]) > z_threshold:
            reasons.append("z")

        bounds = hard_thresholds.get(factor, {})
        direction = None
        if "high" in bounds and r["value"] >= bounds["high"]:
            reasons.append("hard_high")
            direction = "high"
        if "low" in bounds and r["value"] <= bounds["low"]:
            reasons.append("hard_low")
            direction = "low"

        if not reasons:
            continue

        meta = factor_meta.get(factor, {})
        direction_text_cfg = meta.get("direction_text", "")
        if isinstance(direction_text_cfg, dict):
            direction_text = direction_text_cfg.get(direction or ("high" if r["z"] and r["z"] > 0 else "low"), "")
        else:
            direction_text = direction_text_cfg

        entry = dict(r)
        entry["label"] = meta.get("label", factor)
        entry["direction_text"] = direction_text
        entry["reasons"] = reasons
        flagged.append(entry)

    return flagged
