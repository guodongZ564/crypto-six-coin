"""一次性脚本：用 v2 回测已经算好的历史合成分，给
data/composite_score_history.parquet 打底，这样动态分档上线第一天就有
足够历史算阈值，不用真的现攒90天。只跑一次，不是每日流程的一部分。
"""

import sys

import pandas as pd

from narrate import live_bands

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    frames = []
    for asset in live_bands.LIVE_ASSETS:
        df = pd.read_parquet(f"backtest/output_v2/scores_{asset}.parquet")
        sub = df[["composite_score"]].reset_index().rename(columns={"index": "date"})
        sub["asset"] = asset
        frames.append(sub[["date", "asset", "composite_score"]])

    combined = pd.concat(frames, ignore_index=True).dropna(subset=["composite_score"])
    combined = combined.sort_values(["date", "asset"]).reset_index(drop=True)
    live_bands.save_history(combined)
    print(f"[seed] 写入 {len(combined)} 行到 {live_bands.HISTORY_PATH}，"
          f"日期范围 {combined['date'].min()} ~ {combined['date'].max()}")


if __name__ == "__main__":
    main()
