"""评分层入口：读因子时间序列 + 打分规则表 → 六币合成分/动作档 → 写
data/scores_timeseries.parquet → Telegram 播报。

跟在 run_daily.py 后面跑（同一个 workflow 里顺序执行），只做打分，不采集
任何新数据——用的是 run_daily.py 已经写进 data/factor_timeseries.parquet
里的当日数据。
"""

import sys
from datetime import date

import pandas as pd
import yaml

from core import alert, rules, score, store

CONFIG_PATH = "config/factors.yaml"
SCORES_PATH = "data/scores_timeseries.parquet"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _result_to_row(result) -> dict:
    row = {
        "date": result.date,
        "asset": result.asset,
        "raw_score": result.raw_score,
        "effective_dimension_weight": result.effective_dimension_weight,
        "regime_score": result.regime_score,
        "regime_multiplier": result.regime_multiplier,
        "composite_score": result.composite_score,
        "action": result.action,
        "action_meaning": result.action_meaning,
        "confidence": result.confidence,
        "valid_factor_count": result.valid_factor_count,
        "total_factor_count": result.total_factor_count,
        "degraded_factors": ",".join(result.degraded_factors),
        "empty_dimensions": ",".join(result.empty_dimensions),
    }
    for dim_name, dim in result.dimensions.items():
        key = alert.DIMENSION_SHORT_LABELS.get(dim_name, dim_name)
        row[f"dim_{key}_score"] = dim.score
        row[f"dim_{key}_valid"] = dim.valid_factor_count
        row[f"dim_{key}_total"] = dim.total_factor_count
    return row


def main():
    config = load_config()
    parquet_path = config["data"]["parquet_path"]
    target_date = date.today().isoformat()

    system_config, factor_rules = rules.load_rule_table()
    history = store.load(parquet_path)

    if target_date not in history["date"].values:
        print(f"[run_scoring] {target_date} 在 {parquet_path} 里还没有数据，run_daily.py 是不是没跑或者跑失败了？跳过打分。")
        return

    regime, coin_results = score.compute_all_scores(history, target_date, system_config, factor_rules)

    rows = [_result_to_row(coin_results[asset]) for asset in rules.ALL_ASSETS]
    scores_df = pd.DataFrame(rows)
    store.upsert_scores(SCORES_PATH, scores_df)

    text = alert.format_score_broadcast(target_date, regime, coin_results, rules.ALL_ASSETS)
    print(text)
    alert.send_telegram_message(text)

    print(f"[run_scoring] 写入 {SCORES_PATH}，regime={regime.regime_score:.3f}（{regime.band_label}）")


if __name__ == "__main__":
    main()
