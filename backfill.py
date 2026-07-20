"""一次性历史回填。跑一次即可，之后靠 run_daily.py 增量追加。

按 collector/资产分批调用 store.upsert，避免一次性拼出全量大表再写盘。
单源失败不影响其余源继续跑，最后打印失败源摘要。
"""

from datetime import date

import ccxt
import yaml

from collectors import ccxt_market, sentiment
from core import store

CONFIG_PATH = "config/factors.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    parquet_path = config["data"]["parquet_path"]
    start_date = config["data"]["backfill_start_date"]
    end_date = date.today().isoformat()

    spot_exchange = getattr(ccxt, config["exchange"]["ccxt_id"])({"enableRateLimit": True})
    futures_exchange = getattr(ccxt, config["exchange"]["funding_ccxt_id"])({"enableRateLimit": True})

    failed_sources = []
    total_rows = 0

    for asset, symbol in config["exchange"]["symbols"].items():
        try:
            df = ccxt_market.collect_ohlcv_factors(asset, symbol, start_date, end_date, exchange=spot_exchange)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] OHLCV factors {asset} ({symbol}): {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"ccxt_ohlcv:{asset}")
            print(f"[backfill][FAIL] OHLCV {asset}: {e}")

    for asset, symbol in config["exchange"]["funding_symbols"].items():
        try:
            df = ccxt_market.collect_funding_rate(asset, symbol, start_date, end_date, exchange=futures_exchange)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] funding_rate {asset} ({symbol}): {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"funding_rate:{asset}")
            print(f"[backfill][FAIL] funding_rate {asset}: {e}")

    try:
        df = sentiment.collect_fear_greed(start_date, end_date)
        store.upsert(parquet_path, df)
        total_rows += len(df)
        print(f"[backfill] fear_greed: {len(df)} rows")
    except Exception as e:
        failed_sources.append("fear_greed")
        print(f"[backfill][FAIL] fear_greed: {e}")

    print(f"[backfill] done. total_rows_written={total_rows} failed_sources={failed_sources}")


if __name__ == "__main__":
    main()
