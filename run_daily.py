"""每日入口：采集当日各源 → 追加去重 → 异动检测 → Telegram 推送 → 打印摘要。

git commit & push 由 .github/workflows/daily.yml 在采集脚本跑完之后单独执行，
本脚本只负责数据落盘与报警。
"""

import sys
from datetime import date

import ccxt
import yaml

from collectors import ccxt_market, sentiment
from core import alert, anomaly, store

CONFIG_PATH = "config/factors.yaml"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    parquet_path = config["data"]["parquet_path"]
    today = date.today().isoformat()

    spot_exchange = getattr(ccxt, config["exchange"]["ccxt_id"])({"enableRateLimit": True})
    futures_exchange = getattr(ccxt, config["exchange"]["funding_ccxt_id"])({"enableRateLimit": True})

    collected_count = 0
    failed_sources = []

    for asset, symbol in config["exchange"]["symbols"].items():
        try:
            df = ccxt_market.collect_ohlcv_factors(asset, symbol, today, today, exchange=spot_exchange)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"ccxt_ohlcv:{asset}")
            print(f"[FAIL] OHLCV {asset}: {e}")

    for asset, symbol in config["exchange"]["funding_symbols"].items():
        try:
            df = ccxt_market.collect_funding_rate(asset, symbol, today, today, exchange=futures_exchange)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"funding_rate:{asset}")
            print(f"[FAIL] funding_rate {asset}: {e}")

    try:
        df = sentiment.collect_fear_greed(today, today)
        store.upsert(parquet_path, df)
        collected_count += len(df)
    except Exception as e:
        failed_sources.append("fear_greed")
        print(f"[FAIL] fear_greed: {e}")

    history = store.load(parquet_path)
    factor_meta = config.get("factor_meta", {})
    anomaly_cfg = config["anomaly"]

    z_results = anomaly.compute_z_scores(history, today, anomaly_cfg)
    flagged = anomaly.flag_anomalies(z_results, anomaly_cfg, factor_meta)

    summary = {
        "collected": collected_count,
        "anomaly_count": len(flagged),
        "failed_sources": len(failed_sources),
    }

    if flagged:
        text = alert.format_alert_message(today, flagged, summary)
    else:
        text = alert.format_no_anomaly_message(today, summary)

    print(text)
    alert.send_telegram_message(text)

    print(f"[SUMMARY] collected={summary['collected']} anomalies={summary['anomaly_count']} failed_sources={failed_sources}")


if __name__ == "__main__":
    main()
