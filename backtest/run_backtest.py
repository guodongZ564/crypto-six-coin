"""回测引擎：逐日 point-in-time 重算六币合成分，跑三组策略对照(A纯翻转/
B纯分档/C合并)，出 IC/分档单调性/策略绩效 + HTML 报告。

不做校准（那是 backtest/calibrate.py 的事），这里就是"用规格2的评分函数，
在历史上老老实实滚一遍，看它到底有没有预测力"。

持有周期是3~20天的波段（日线技术面+衍生品情绪+月频regime决定的），逐日
(不是逐周/逐月)重算是因为策略要每天看当日分数决定要不要调仓，跟持有周期
长短是两回事——测的是"这套每日更新的评分能不能指导3~20天的仓位"。
"""

import sys

import pandas as pd

from backtest import metrics, point_in_time, strategy
from core import rules, score, store

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FACTOR_TIMESERIES_PATH = "data/factor_timeseries.parquet"
FORWARD_HORIZONS = [3, 7, 14]
DEFAULT_FEE_RATE = 0.0005  # 单边 0.05%
BURN_IN_DAYS = 90  # 让趋势/分位类归一化有基线可用


def _daily_score_series(full_history: pd.DataFrame, vintage_cache: pd.DataFrame, system_config, factor_rules, dates: list) -> dict:
    """逐日跑 compute_all_scores，返回 {asset: DataFrame(date, composite_score, action, raw_score, valid, total)}。"""
    per_asset_rows = {asset: [] for asset in rules.ALL_ASSETS}

    for i, d in enumerate(dates):
        pit_history = point_in_time.build_point_in_time_history(full_history, vintage_cache, d)
        regime, coin_results = score.compute_all_scores(pit_history, d, system_config, factor_rules)

        for asset in rules.ALL_ASSETS:
            r = coin_results[asset]
            per_asset_rows[asset].append({
                "date": d,
                "composite_score": r.composite_score,
                "action": r.action,
                "raw_score": r.raw_score,
                "valid_factor_count": r.valid_factor_count,
                "total_factor_count": r.total_factor_count,
                "empty_dimensions": len(r.empty_dimensions),
            })

        if (i + 1) % 200 == 0:
            print(f"[backtest] 已重算 {i + 1}/{len(dates)} 天")

    return {asset: pd.DataFrame(rows).set_index("date") for asset, rows in per_asset_rows.items()}


def _close_price_series(full_history: pd.DataFrame, asset: str) -> pd.Series:
    sub = full_history[(full_history["asset"] == asset) & (full_history["factor"] == "close_price")]
    return sub.sort_values("date").set_index("date")["value"]


def _simulate_group(scores_df: pd.DataFrame, close: pd.Series, group: str, clear_line: float, fee_rate: float) -> dict:
    dates = scores_df.index.intersection(close.index)
    dates = sorted(dates)

    daily_ret = close.reindex(dates).pct_change().fillna(0)

    positions = []
    flip_state = strategy.FlipState()
    prev_position = 0.0
    for d in dates:
        s = scores_df.loc[d, "composite_score"]
        if group == "A":
            pos = strategy.flip_target_position(s, flip_state, clear_line)
        elif group == "B":
            pos = strategy.tiered_target_position(s)
        elif group == "C":
            pos = strategy.merged_target_position(s, clear_line)
        else:
            raise ValueError(f"unknown group {group}")
        positions.append(pos)

    positions = pd.Series(positions, index=dates)
    position_yesterday = positions.shift(1).fillna(0)
    position_change = (positions - position_yesterday).abs()
    friction = position_change.apply(lambda c: strategy.apply_friction(c, fee_rate))

    strategy_daily_return = position_yesterday * daily_ret - friction

    perf = metrics.strategy_performance(strategy_daily_return, positions)
    perf["positions"] = positions
    perf["daily_return"] = strategy_daily_return
    return perf


def main(start_date: str | None = None, end_date: str | None = None, clear_line: float = strategy.DEFAULT_CLEAR_LINE, fee_rate: float = DEFAULT_FEE_RATE):
    system_config, factor_rules = rules.load_rule_table()
    full_history = store.load(FACTOR_TIMESERIES_PATH)
    vintage_cache = point_in_time.load_vintage_cache()

    btc_close = _close_price_series(full_history, "BTC")
    if start_date is None:
        start_date = (pd.Timestamp(btc_close.index.min()) + pd.Timedelta(days=BURN_IN_DAYS)).strftime("%Y-%m-%d")
    if end_date is None:
        max_horizon = max(FORWARD_HORIZONS)
        end_date = (pd.Timestamp(full_history["date"].max()) - pd.Timedelta(days=max_horizon)).strftime("%Y-%m-%d")

    dates = pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d").tolist()
    print(f"[backtest] 回测区间 {start_date} ~ {end_date}，共 {len(dates)} 天")

    per_asset_scores = _daily_score_series(full_history, vintage_cache, system_config, factor_rules, dates)

    results = {}
    for asset in rules.ALL_ASSETS:
        scores_df = per_asset_scores[asset]
        close = _close_price_series(full_history, asset)
        if close.empty:
            print(f"[backtest] {asset} 没有 close_price 数据，跳过")
            continue

        ic_results = {}
        for horizon in FORWARD_HORIZONS:
            fwd_ret = metrics.forward_return(close, horizon).reindex(scores_df.index)
            ic_results[horizon] = metrics.rank_ic(scores_df["composite_score"], fwd_ret)

        action_order = [b.action for b in system_config.action_bands]
        mono_tables = {}
        for horizon in FORWARD_HORIZONS:
            fwd_ret = metrics.forward_return(close, horizon).reindex(scores_df.index)
            mono_tables[horizon] = metrics.monotonicity_table(scores_df["action"], fwd_ret, action_order)

        group_perf = {}
        for group in ["A", "B", "C"]:
            group_perf[group] = _simulate_group(scores_df, close, group, clear_line, fee_rate)

        avg_coverage = (scores_df["valid_factor_count"] / scores_df["total_factor_count"].replace(0, pd.NA)).mean()

        results[asset] = {
            "scores_df": scores_df,
            "ic_results": ic_results,
            "monotonicity": mono_tables,
            "group_performance": group_perf,
            "avg_coverage": float(avg_coverage) if pd.notna(avg_coverage) else None,
        }
        print(f"[backtest] {asset} 完成：avg_coverage={results[asset]['avg_coverage']}")

    return results, {"start_date": start_date, "end_date": end_date, "clear_line": clear_line, "fee_rate": fee_rate}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--clear-line", type=float, default=strategy.DEFAULT_CLEAR_LINE)
    parser.add_argument("--fee-rate", type=float, default=DEFAULT_FEE_RATE)
    args = parser.parse_args()

    results, meta = main(args.start_date, args.end_date, args.clear_line, args.fee_rate)
    print(meta)
