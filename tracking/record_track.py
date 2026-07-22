"""每日评分实盘留痕：data/scoring_track.parquet，跟现有的
factor_timeseries.parquet / scores_timeseries.parquet / composite_score_history.parquet
都不是一回事，专门用于"3个月后拿真实未来数据验证评分到底有没有预测力"。

跟回测的区别：回测是point-in-time重演历史，这个是记录当时的真实预测、
再用后来真实发生的价格验证——是更硬的证据，不依赖任何历史重算逻辑。

只记 BTC/ETH/SOL（评分已冻结的 UNI/LINK/LTC 没有综合分可记）。

事后不可改是硬约束：
- append_today 只在"今天这个asset还没记录过"时才插入新行，已经记过的绝不
  用重新算出来的值覆盖——即使同一天因为某种原因被重复调用，也不会篡改
  已经落盘的历史真实记录。
- backfill_forward_returns 只填充还是 None 的未来收益列，任何已经有值的
  格子绝不重新计算、绝不覆盖。
- 两个函数都不touch composite_score/action/close_price这几个"当天"字段，
  只有 append_today 第一次写入时会设置它们，之后永远只读不写。
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

from core import store
from narrate import prepare_report

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TRACK_PATH = "data/scoring_track.parquet"
HORIZONS = [3, 7, 14]

SCHEMA_COLUMNS = (
    ["date", "asset", "composite_score", "action", "close_price"]
    + [f"fwd_{h}d_close" for h in HORIZONS]
    + [f"fwd_{h}d_pct" for h in HORIZONS]
)


def load_track(path: str = TRACK_PATH) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.read_parquet(p)


def _close_price_on(factor_history: pd.DataFrame, asset: str, target_date: str):
    sub = factor_history[
        (factor_history["asset"] == asset)
        & (factor_history["factor"] == "close_price")
        & (factor_history["date"] == target_date)
    ]
    if sub.empty:
        return None
    return float(sub["value"].iloc[0])


def append_today(track_df: pd.DataFrame, target_date: str, factor_history: pd.DataFrame, coin_score_by_asset: dict) -> pd.DataFrame:
    already_recorded = set(track_df[track_df["date"] == target_date]["asset"])

    new_rows = []
    for asset in prepare_report.LIVE_ASSETS:
        if asset in already_recorded:
            continue
        coin = coin_score_by_asset.get(asset)
        if coin is None:
            continue
        close_price = _close_price_on(factor_history, asset, target_date)
        row = {
            "date": target_date,
            "asset": asset,
            "composite_score": coin["composite_score"],
            "action": coin["action"],
            "close_price": close_price,
        }
        for h in HORIZONS:
            row[f"fwd_{h}d_close"] = None
            row[f"fwd_{h}d_pct"] = None
        new_rows.append(row)

    if not new_rows:
        return track_df

    new_df = pd.DataFrame(new_rows, columns=SCHEMA_COLUMNS)
    return pd.concat([track_df, new_df], ignore_index=True)


def backfill_forward_returns(track_df: pd.DataFrame, factor_history: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """只填充还是 None 的未来收益格子；到期了但当天数据还没采到就跳过，
    留到下次运行再试，绝不用近似值顶替。"""
    track_df = track_df.copy()

    for h in HORIZONS:
        close_col = f"fwd_{h}d_close"
        pct_col = f"fwd_{h}d_pct"
        missing_idx = track_df.index[track_df[close_col].isna()]

        for idx in missing_idx:
            row_date = track_df.at[idx, "date"]
            maturity_date = (pd.Timestamp(row_date) + pd.Timedelta(days=h)).strftime("%Y-%m-%d")
            if maturity_date > target_date:
                continue

            asset = track_df.at[idx, "asset"]
            future_close = _close_price_on(factor_history, asset, maturity_date)
            if future_close is None:
                continue

            base_close = track_df.at[idx, "close_price"]
            track_df.at[idx, close_col] = future_close
            if base_close:
                track_df.at[idx, pct_col] = (future_close / base_close - 1) * 100

    return track_df


def update(track_path: str = TRACK_PATH) -> pd.DataFrame:
    config = prepare_report.load_config()
    target_date = date.today().isoformat()
    factor_history = store.load(config["data"]["parquet_path"])

    payload = prepare_report.prepare(target_date)
    coin_score_by_asset = {c["asset"]: c for c in payload["coins"]}

    track_df = load_track(track_path)
    track_df = append_today(track_df, target_date, factor_history, coin_score_by_asset)
    track_df = backfill_forward_returns(track_df, factor_history, target_date)
    track_df = track_df.sort_values(["date", "asset"]).reset_index(drop=True)

    out_path = Path(track_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    track_df.to_parquet(out_path, index=False)
    print(f"[scoring_track] 更新完成，共 {len(track_df)} 行")
    return track_df


if __name__ == "__main__":
    update()
