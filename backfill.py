"""一次性历史回填。跑一次即可，之后靠 run_daily.py 增量追加。

按 collector/资产分批调用 store.upsert，避免一次性拼出全量大表再写盘。
单源失败不影响其余源继续跑，最后打印失败源摘要。
"""

from datetime import date

import ccxt
import yaml

from collectors import ccxt_market, coinbase_premium, cryptoquant, defillama, deribit, fred, sentiment
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

    for asset, ccy in config["exchange"]["oi_ccy"].items():
        try:
            df = ccxt_market.collect_open_interest(asset, ccy, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] open_interest {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"open_interest:{asset}")
            print(f"[backfill][FAIL] open_interest {asset}: {e}")

    for asset, inst_id in config["exchange"]["long_short_inst_id"].items():
        try:
            df = ccxt_market.collect_long_short_ratio(asset, inst_id, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] long_short_ratio {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"long_short_ratio:{asset}")
            print(f"[backfill][FAIL] long_short_ratio {asset}: {e}")

    try:
        df = sentiment.collect_fear_greed(start_date, end_date)
        store.upsert(parquet_path, df)
        total_rows += len(df)
        print(f"[backfill] fear_greed: {len(df)} rows")
    except Exception as e:
        failed_sources.append("fear_greed")
        print(f"[backfill][FAIL] fear_greed: {e}")

    try:
        macro_start = config["data"]["macro_backfill_start_date"]
        df = fred.collect_macro_factors(macro_start, end_date, config["fred"]["series"])
        store.upsert(parquet_path, df)
        total_rows += len(df)
        print(f"[backfill] fred macro: {len(df)} rows")
    except Exception as e:
        failed_sources.append("fred_macro")
        print(f"[backfill][FAIL] fred macro: {e}")

    for asset, currency in config["deribit"]["currencies"].items():
        try:
            df = deribit.collect_dvol(asset, currency, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] dvol {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"dvol:{asset}")
            print(f"[backfill][FAIL] dvol {asset}: {e}")

    for asset, chain in config["defillama"]["chain_tvl"].items():
        try:
            df = defillama.collect_chain_tvl(asset, chain, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] chain_tvl {asset} ({chain}): {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"chain_tvl:{asset}")
            print(f"[backfill][FAIL] chain_tvl {asset}: {e}")

    try:
        df = defillama.collect_stablecoin_mcap(start_date, end_date)
        store.upsert(parquet_path, df)
        total_rows += len(df)
        print(f"[backfill] stablecoin_mcap: {len(df)} rows")
    except Exception as e:
        failed_sources.append("stablecoin_mcap")
        print(f"[backfill][FAIL] stablecoin_mcap: {e}")

    for asset, protocol in config["defillama"]["dex_protocols"].items():
        try:
            df = defillama.collect_dex_volume(asset, protocol, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] dex_volume {asset} ({protocol}): {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"dex_volume:{asset}")
            print(f"[backfill][FAIL] dex_volume {asset}: {e}")

    for asset, protocol in config["defillama"]["fee_protocols"].items():
        try:
            df = defillama.collect_protocol_fees(asset, protocol, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] protocol_fees {asset} ({protocol}): {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"protocol_fees:{asset}")
            print(f"[backfill][FAIL] protocol_fees {asset}: {e}")

    for asset, cq_asset in config["cryptoquant"]["netflow_assets"].items():
        try:
            df = cryptoquant.collect_exchange_netflow(asset, cq_asset, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] exchange_netflow {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"exchange_netflow:{asset}")
            print(f"[backfill][FAIL] exchange_netflow {asset}: {e}")

    for asset, cq_asset in config["cryptoquant"]["pnl_supply_assets"].items():
        try:
            df = cryptoquant.collect_supply_pnl(asset, cq_asset, start_date, end_date)
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] supply_pnl {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"supply_pnl:{asset}")
            print(f"[backfill][FAIL] supply_pnl {asset}: {e}")

    for asset, spec in config["coinbase_premium"].items():
        try:
            df = coinbase_premium.collect_premium(
                asset, spec["coinbase_product"], spec["ref_symbol"], start_date, end_date, ref_exchange=spot_exchange
            )
            store.upsert(parquet_path, df)
            total_rows += len(df)
            print(f"[backfill] coinbase_premium {asset}: {len(df)} rows")
        except Exception as e:
            failed_sources.append(f"coinbase_premium:{asset}")
            print(f"[backfill][FAIL] coinbase_premium {asset}: {e}")

    print(f"[backfill] done. total_rows_written={total_rows} failed_sources={failed_sources}")


if __name__ == "__main__":
    main()
