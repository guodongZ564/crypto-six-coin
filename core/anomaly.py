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

        # 月度/低频宏观因子按日forward-fill后，窗口内经常连续几十天数值完全
        # 不变，std 算出来不是精确的0而是浮点噪声(~1e-16)。除以这种"约等于0"
        # 的std会把一次正常的小幅变化放大成几十万亿倍标准差的假异动
        # (实测 core_pce: mean=3.412, std=4.47e-16 → z=-2.8e14)。用相对于
        # 数值量级的下限判断"这个窗口其实没有真实波动"，跳过z值计算，而不是
        # 硬算出一个没有统计意义的数字。
        min_meaningful_sigma = max(abs(mu), 1.0) * 1e-9
        if sigma < min_meaningful_sigma:
            results.append({
                "asset": asset,
                "factor": factor,
                "value": today_value,
                "mean": mu,
                "std": sigma,
                "z": None,
                "status": "insufficient_variance",
            })
            continue

        z = (today_value - mu) / sigma

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
