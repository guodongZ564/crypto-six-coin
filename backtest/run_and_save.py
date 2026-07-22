"""跑 run_backtest.main() 并把结果落盘到 backtest/output/，供之后单独生成
报告用——回测一次要跑几分钟到十几分钟，不想每次改报告样式都重新跑一遍。
"""

import json
import sys
from pathlib import Path

import pandas as pd

from backtest import run_backtest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path("backtest/output")


def _serialize_perf(perf: dict) -> dict:
    return {k: v for k, v in perf.items() if k not in ("positions", "daily_return", "equity_curve")}


def main(start_date=None, end_date=None, clear_line=None, fee_rate=None, assets=None, use_dynamic_bands=False, output_dir=None):
    kwargs = {}
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    if clear_line is not None:
        kwargs["clear_line"] = clear_line
    if fee_rate is not None:
        kwargs["fee_rate"] = fee_rate
    if assets is not None:
        kwargs["assets"] = assets
    kwargs["use_dynamic_bands"] = use_dynamic_bands

    results, meta = run_backtest.main(**kwargs)

    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {"meta": meta, "assets": {}}
    for asset, r in results.items():
        r["scores_df"].to_parquet(output_dir / f"scores_{asset}.parquet")

        for group, perf in r["group_performance"].items():
            perf["equity_curve"].rename("equity").to_frame().to_parquet(output_dir / f"equity_{asset}_{group}.parquet")
            perf["positions"].rename("position").to_frame().to_parquet(output_dir / f"positions_{asset}_{group}.parquet")

        mono_serialized = {}
        for h, table in r["monotonicity"].items():
            mono_serialized[str(h)] = table.reset_index().to_dict(orient="records")

        summary["assets"][asset] = {
            "avg_coverage": r["avg_coverage"],
            "ic_results": {str(h): v for h, v in r["ic_results"].items()},
            "monotonicity": mono_serialized,
            "group_performance": {g: _serialize_perf(p) for g, p in r["group_performance"].items()},
        }

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"[run_and_save] 结果已写入 {output_dir}/")
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--clear-line", type=float)
    parser.add_argument("--fee-rate", type=float)
    args = parser.parse_args()

    main(args.start_date, args.end_date, args.clear_line, args.fee_rate)
