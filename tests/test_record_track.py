"""评分实盘留痕的核心保证：事后不可改。这几个测试专门钉死"历史行的分数/
动作/已经回填的未来收益，绝不会被后续调用覆盖或重算"——这是留痕数据要
拿来做3个月后诚实验证的前提，测试比代码审查更硬。
"""

import pandas as pd
import pytest

from tracking import record_track


def _factor_history(rows):
    return pd.DataFrame(rows, columns=["date", "asset", "factor", "value", "source"])


def test_append_today_does_not_duplicate_or_overwrite_same_day():
    track_df = pd.DataFrame(
        [{"date": "2026-07-20", "asset": "BTC", "composite_score": -0.5, "action": "看空", "close_price": 100,
          "fwd_3d_close": None, "fwd_3d_pct": None, "fwd_7d_close": None, "fwd_7d_pct": None,
          "fwd_14d_close": None, "fwd_14d_pct": None}],
        columns=record_track.SCHEMA_COLUMNS,
    )
    factor_history = _factor_history([("2026-07-20", "BTC", "close_price", 999, "test")])
    # 故意传一个跟已有记录不同的分数，验证 append_today 不会覆盖旧值
    coin_score_by_asset = {"BTC": {"composite_score": +0.9, "action": "看多"}}

    result = record_track.append_today(track_df, "2026-07-20", factor_history, coin_score_by_asset)

    assert len(result) == 1
    assert result.iloc[0]["composite_score"] == -0.5
    assert result.iloc[0]["action"] == "看空"
    assert result.iloc[0]["close_price"] == 100


def test_append_today_adds_new_assets_for_new_date():
    track_df = pd.DataFrame(columns=record_track.SCHEMA_COLUMNS)
    factor_history = _factor_history([
        ("2026-07-21", "BTC", "close_price", 100, "test"),
        ("2026-07-21", "ETH", "close_price", 50, "test"),
        ("2026-07-21", "SOL", "close_price", 20, "test"),
    ])
    coin_score_by_asset = {
        "BTC": {"composite_score": 0.5, "action": "看多"},
        "ETH": {"composite_score": -0.2, "action": "中性"},
        "SOL": {"composite_score": 0.1, "action": "中性"},
    }

    result = record_track.append_today(track_df, "2026-07-21", factor_history, coin_score_by_asset)

    assert len(result) == 3
    assert set(result["asset"]) == {"BTC", "ETH", "SOL"}
    assert all(result["fwd_7d_close"].isna())


def test_backfill_only_fills_missing_and_never_overwrites_existing():
    track_df = pd.DataFrame(
        [
            {"date": "2026-07-01", "asset": "BTC", "composite_score": 0.5, "action": "看多", "close_price": 100,
             "fwd_3d_close": 110, "fwd_3d_pct": 10.0,  # 已经回填过，必须原样保留
             "fwd_7d_close": None, "fwd_7d_pct": None,
             "fwd_14d_close": None, "fwd_14d_pct": None},
        ],
        columns=record_track.SCHEMA_COLUMNS,
    )
    # 7天到期日(2026-07-08)有真实收盘价120；如果覆盖逻辑有bug把3日列也重算，
    # 会被这个测试的断言抓到
    factor_history = _factor_history([
        ("2026-07-08", "BTC", "close_price", 120, "test"),
    ])

    result = record_track.backfill_forward_returns(track_df, factor_history, "2026-07-08")

    # 已经回填过的3日列必须纹丝不动
    assert result.iloc[0]["fwd_3d_close"] == 110
    assert result.iloc[0]["fwd_3d_pct"] == 10.0
    # 到期的7日列应该被正确填上
    assert result.iloc[0]["fwd_7d_close"] == 120
    assert result.iloc[0]["fwd_7d_pct"] == pytest.approx(20.0)
    # 还没到期的14日列应该还是 None
    assert pd.isna(result.iloc[0]["fwd_14d_close"])


def test_backfill_skips_when_not_yet_matured():
    track_df = pd.DataFrame(
        [{"date": "2026-07-20", "asset": "BTC", "composite_score": 0.5, "action": "看多", "close_price": 100,
          "fwd_3d_close": None, "fwd_3d_pct": None, "fwd_7d_close": None, "fwd_7d_pct": None,
          "fwd_14d_close": None, "fwd_14d_pct": None}],
        columns=record_track.SCHEMA_COLUMNS,
    )
    factor_history = _factor_history([("2026-07-21", "BTC", "close_price", 105, "test")])

    # target_date 只比记录日期晚1天，3日窗口还没到期
    result = record_track.backfill_forward_returns(track_df, factor_history, "2026-07-21")

    assert pd.isna(result.iloc[0]["fwd_3d_close"])


def test_backfill_skips_when_matured_but_future_price_not_collected_yet():
    track_df = pd.DataFrame(
        [{"date": "2026-07-01", "asset": "BTC", "composite_score": 0.5, "action": "看多", "close_price": 100,
          "fwd_3d_close": None, "fwd_3d_pct": None, "fwd_7d_close": None, "fwd_7d_pct": None,
          "fwd_14d_close": None, "fwd_14d_pct": None}],
        columns=record_track.SCHEMA_COLUMNS,
    )
    # 到期了(2026-07-04)但那天的价格数据缺失(采集失败之类)
    factor_history = _factor_history([("2026-07-01", "BTC", "close_price", 100, "test")])

    result = record_track.backfill_forward_returns(track_df, factor_history, "2026-07-05")

    assert pd.isna(result.iloc[0]["fwd_3d_close"])
