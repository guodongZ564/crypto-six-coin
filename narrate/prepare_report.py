"""组装叙事层的输入数据：全是代码算好的确定性数字，叙事层(narrator.py)只
负责把这些数字翻译成中文，不得自己算、不得推翻分数。

只做 BTC/ETH/SOL——按用户定的校准结论，UNI/LINK/LTC 评分禁用（负IC，评分
会误导），数据采集不受影响继续跑。

分档/目标仓位用 B/C 合并逻辑（backtest.strategy.merged_target_position），
不是 A 组纯翻转——A 组的高收益是拿深回撤换的，现实里拿不住，日报的仓位
建议必须基于 B/C 才是能真实执行的那个。B/C 在现货版下数学恒等（已有单测
钉死），这里统一调 merged_target_position。

阈值走动态分档（narrate.live_bands，跟 backtest.dynamic_bands 同一套口径:
BTC/ETH/SOL 池化的历史70/90分位，严格早于当天，不会被今天自己的分数
影响）而不是 core/score.py 里 xlsx 解析出来的固定 ±0.4/±1.0——这是校准
定型的 v2 版本，固定表已经被验证过"强烈看多/看空几乎不触发"这个问题。
"""

import yaml

from backtest import strategy
from backtest.dynamic_bands import classify_action
from core import anomaly, rules, score, store
from narrate import live_bands

CONFIG_PATH = "config/factors.yaml"

LIVE_ASSETS = ["BTC", "ETH", "SOL"]

# 三币回测可信度——数字全部来自 backtest/output_v2/summary.json 的真实结果
# （2018-04-11~2026-07-07，3010天），叙事层只能引用这些数字定语气，不能
# 自己评价"这个币准不准"。
BACKTEST_CREDIBILITY = {
    "SOL": {
        "tier": "强",
        "ic_7d": 0.091,
        "t_stat_7d": 4.20,
        "group_b_annualized_pct": 70.5,
        "group_b_sharpe": 1.65,
        "note": "IC最强、5档收益单调递减、B组年化70.5%/夏普1.65——三币里回测可信度最高",
    },
    "ETH": {
        "tier": "中",
        "ic_7d": 0.041,
        "t_stat_7d": 2.26,
        "group_b_annualized_pct": 4.8,
        "group_b_sharpe": 0.32,
        "note": "7日IC中等但显著，14日IC更强(0.078,t=4.3)；B组年化4.8%，比BTC强但明显不如SOL",
    },
    "BTC": {
        "tier": "弱-仅方向参考",
        "ic_7d": 0.038,
        "t_stat_7d": 2.07,
        "group_b_annualized_pct": 1.4,
        "group_b_sharpe": 0.17,
        "note": "IC边缘显著、B组年化仅1.4%/夏普0.17，择时优势薄，只能当方向参考，不能当仓位依据",
    },
}


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def prepare(target_date: str) -> dict:
    config = load_config()
    system_config, factor_rules = rules.load_rule_table()
    factor_history = store.load(config["data"]["parquet_path"])

    regime, coin_results = score.compute_all_scores(factor_history, target_date, system_config, factor_rules)

    score_hist = live_bands.load_history()
    t70, t90 = live_bands.compute_today_thresholds(score_hist, target_date)

    coins_payload = []
    for asset in LIVE_ASSETS:
        r = coin_results[asset]
        composite = r.composite_score

        if composite is None:
            action = "无法评分"
            target_position_pct = 0.0
        elif t70 is None or t90 is None:
            action = "中性 / 观望"  # 动态阈值历史不足，先按中性处理，不硬凑
            target_position_pct = 0.0
        else:
            action = classify_action(composite, t70, t90)
            target_position_pct = strategy.merged_target_position(
                composite, clear_line=strategy.DEFAULT_CLEAR_LINE, entry_threshold=t70, full_threshold=t90,
            ) * 100

        coins_payload.append({
            "asset": asset,
            "composite_score": composite,
            "action": action,
            "target_position_pct": target_position_pct,
            "confidence_pct": (r.confidence * 100) if r.confidence is not None else None,
            "valid_factor_count": r.valid_factor_count,
            "total_factor_count": r.total_factor_count,
            "dimensions": {
                name: {"score": d.score, "valid": d.valid_factor_count, "total": d.total_factor_count}
                for name, d in r.dimensions.items()
            },
            "degraded_factors": r.degraded_factors,
            "backtest_credibility": BACKTEST_CREDIBILITY[asset],
        })

    anomaly_cfg = config["anomaly"]
    factor_meta = config.get("factor_meta", {})
    z_results = anomaly.compute_z_scores(factor_history, target_date, anomaly_cfg)
    flagged = anomaly.flag_anomalies(z_results, anomaly_cfg, factor_meta)
    live_anomalies = [a for a in flagged if a["asset"] in LIVE_ASSETS + ["MARKET", "MACRO"]]

    payload = {
        "date": target_date,
        "regime": {
            "regime_score": regime.regime_score,
            "band_label": regime.band_label,
            "macro_valid": regime.macro_dimension.valid_factor_count,
            "macro_total": regime.macro_dimension.total_factor_count,
            "cycle_valid": regime.cycle_dimension.valid_factor_count,
            "cycle_total": regime.cycle_dimension.total_factor_count,
        },
        "coins": coins_payload,
        "anomalies": [
            {
                "asset": a["asset"],
                "factor": a.get("label", a["factor"]),
                "z": a.get("z"),
                "value": a["value"],
                "direction_text": a.get("direction_text"),
            }
            for a in live_anomalies
        ],
        "dynamic_bands": {"threshold_70": t70, "threshold_90": t90},
    }

    today_scores = {c["asset"]: c["composite_score"] for c in coins_payload}
    updated_hist = live_bands.append_today(score_hist, target_date, today_scores)
    live_bands.save_history(updated_hist)

    return payload
