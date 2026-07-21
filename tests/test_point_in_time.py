"""规格3验收标准第1条的具体落地：随机抽查一个历史日 t，用"截断到 date<=t
的历史" 和 "完整历史（含 t 之后的数据）" 分别重算 t 这天的评分，结果必须
逐位一致——如果不一致，说明评分链路某处偷看了未来。

这比代码审查更硬：只要 normalize.py/score.py 里任何一处不小心绕过了
ctx.history 的过滤、直接摸到了完整 DataFrame 里 t 之后的行，这个测试就会
在 full_history 版本里得到跟 truncated 版本不一样的结果，从而暴露出来。
"""

import pytest

from backtest import point_in_time
from core import rules, score, store

SAMPLE_DATE = "2024-06-15"  # 主抽查日：历史中段，前后都有充足数据，不是回测窗口边界
EXTRA_SAMPLE_DATES = ["2021-09-10", "2023-01-20", "2025-11-05"]  # 额外多抽几个不同时期


@pytest.fixture(scope="module")
def full_history():
    df = store.load("data/factor_timeseries.parquet")
    if df.empty:
        pytest.skip("data/factor_timeseries.parquet 没有数据，跳过（需要先跑过 backfill.py）")
    return df


@pytest.fixture(scope="module")
def vintage_cache():
    return point_in_time.load_vintage_cache()


@pytest.fixture(scope="module")
def rule_config():
    return rules.load_rule_table()


def test_sample_date_has_future_data_to_actually_test_against(full_history):
    assert full_history["date"].max() > SAMPLE_DATE, (
        "测试数据里没有比抽查日更晚的行，这个自证测试就测不出偷看未来的问题"
    )


@pytest.mark.parametrize("sample_date", [SAMPLE_DATE, *EXTRA_SAMPLE_DATES])
def test_truncated_and_full_history_give_identical_scores(full_history, vintage_cache, rule_config, sample_date):
    system_config, factor_rules = rule_config

    if full_history["date"].max() <= sample_date or full_history["date"].min() > sample_date:
        pytest.skip(f"{sample_date} 不在当前历史数据范围内")

    truncated_history = full_history[full_history["date"] <= sample_date].reset_index(drop=True)

    pit_from_full = point_in_time.build_point_in_time_history(full_history, vintage_cache, sample_date)
    pit_from_truncated = point_in_time.build_point_in_time_history(truncated_history, vintage_cache, sample_date)

    regime_full, coins_full = score.compute_all_scores(pit_from_full, sample_date, system_config, factor_rules)
    regime_trunc, coins_trunc = score.compute_all_scores(pit_from_truncated, sample_date, system_config, factor_rules)

    assert regime_full.regime_score == regime_trunc.regime_score
    assert regime_full.long_mult == regime_trunc.long_mult

    for asset in rules.ALL_ASSETS:
        r_full = coins_full[asset]
        r_trunc = coins_trunc[asset]
        assert r_full.raw_score == r_trunc.raw_score, f"{sample_date} {asset} raw_score 不一致"
        assert r_full.composite_score == r_trunc.composite_score, f"{sample_date} {asset} composite_score 不一致"
        assert r_full.valid_factor_count == r_trunc.valid_factor_count, f"{sample_date} {asset} valid_factor_count 不一致"
        assert r_full.action == r_trunc.action, f"{sample_date} {asset} action 不一致"
