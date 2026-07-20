"""每日入口：采集当日各源 → 追加去重 → 异动检测 → Telegram 推送 → 打印摘要。

git commit & push 由 .github/workflows/daily.yml 在采集脚本跑完之后单独执行，
本脚本只负责数据落盘与报警。
"""

import sys
from datetime import date

import ccxt
import yaml

from collectors import ccxt_market, coinbase_premium, cryptoquant, defillama, deribit, fred, sentiment
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

    for asset, ccy in config["exchange"]["oi_ccy"].items():
        try:
            df = ccxt_market.collect_open_interest(asset, ccy, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"open_interest:{asset}")
            print(f"[FAIL] open_interest {asset}: {e}")

    for asset, inst_id in config["exchange"]["long_short_inst_id"].items():
        try:
            df = ccxt_market.collect_long_short_ratio(asset, inst_id, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"long_short_ratio:{asset}")
            print(f"[FAIL] long_short_ratio {asset}: {e}")

    try:
        df = sentiment.collect_fear_greed(today, today)
        store.upsert(parquet_path, df)
        collected_count += len(df)
    except Exception as e:
        failed_sources.append("fear_greed")
        print(f"[FAIL] fear_greed: {e}")

    try:
        df = fred.collect_macro_factors(today, today, config["fred"]["series"])
        store.upsert(parquet_path, df)
        collected_count += len(df)
    except Exception as e:
        failed_sources.append("fred_macro")
        print(f"[FAIL] fred macro: {e}")

    for asset, currency in config["deribit"]["currencies"].items():
        try:
            df = deribit.collect_dvol(asset, currency, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"dvol:{asset}")
            print(f"[FAIL] dvol {asset}: {e}")

    for asset, chain in config["defillama"]["chain_tvl"].items():
        try:
            df = defillama.collect_chain_tvl(asset, chain, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"chain_tvl:{asset}")
            print(f"[FAIL] chain_tvl {asset}: {e}")

    try:
        df = defillama.collect_stablecoin_mcap(today, today)
        store.upsert(parquet_path, df)
        collected_count += len(df)
    except Exception as e:
        failed_sources.append("stablecoin_mcap")
        print(f"[FAIL] stablecoin_mcap: {e}")

    for asset, protocol in config["defillama"]["dex_protocols"].items():
        try:
            df = defillama.collect_dex_volume(asset, protocol, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"dex_volume:{asset}")
            print(f"[FAIL] dex_volume {asset}: {e}")

    for asset, protocol in config["defillama"]["fee_protocols"].items():
        try:
            df = defillama.collect_protocol_fees(asset, protocol, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"protocol_fees:{asset}")
            print(f"[FAIL] protocol_fees {asset}: {e}")

    for asset, cq_asset in config["cryptoquant"]["netflow_assets"].items():
        try:
            df = cryptoquant.collect_exchange_netflow(asset, cq_asset, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"exchange_netflow:{asset}")
            print(f"[FAIL] exchange_netflow {asset}: {e}")

    for asset, cq_asset in config["cryptoquant"]["pnl_supply_assets"].items():
        try:
            df = cryptoquant.collect_supply_pnl(asset, cq_asset, today, today)
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"supply_pnl:{asset}")
            print(f"[FAIL] supply_pnl {asset}: {e}")

    for asset, spec in config["coinbase_premium"].items():
        try:
            df = coinbase_premium.collect_premium(
                asset, spec["coinbase_product"], spec["ref_symbol"], today, today, ref_exchange=spot_exchange
            )
            store.upsert(parquet_path, df)
            collected_count += len(df)
        except Exception as e:
            failed_sources.append(f"coinbase_premium:{asset}")
            print(f"[FAIL] coinbase_premium {asset}: {e}")

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
