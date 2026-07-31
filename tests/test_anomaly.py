"""异动检测的除零/近零标准差保护：月度宏观因子forward-fill后窗口内长期
持平，std会塌缩成浮点噪声(~1e-16)，除出来的z值会是没有意义的天文数字。
这几个测试钉死"近零标准差的窗口必须跳过z值计算"，不能让一次正常的小幅
变化被误报成几十万亿倍标准差的假异动。
"""

import pandas as pd

from core import anomaly


def _flat_then_change_history(flat_value, changed_value, n_days=95):
    dates = pd.date_range("2026-01-01", periods=n_days, freq="D")
    rows = []
    for i, d in enumerate(dates[:-1]):
        rows.append((d.strftime("%Y-%m-%d"), "MACRO", "core_pce", flat_value, "fred"))
    rows.append((dates[-1].strftime("%Y-%m-%d"), "MACRO", "core_pce", changed_value, "fred"))
    return pd.DataFrame(rows, columns=["date", "asset", "factor", "value", "source"])


def test_near_zero_std_from_flat_window_is_skipped_not_computed():
    history = _flat_then_change_history(flat_value=3.41204, changed_value=3.28653)
    target_date = history["date"].iloc[-1]

    results = anomaly.compute_z_scores(history, target_date, {"window_days": 90, "min_window_days": 30})

    assert len(results) == 1
    r = results[0]
    assert r["status"] == "insufficient_variance"
    assert r["z"] is None


def test_insufficient_variance_rows_are_never_flagged_as_anomalies():
    history = _flat_then_change_history(flat_value=3.41204, changed_value=3.28653)
    target_date = history["date"].iloc[-1]

    results = anomaly.compute_z_scores(history, target_date, {"window_days": 90, "min_window_days": 30})
    flagged = anomaly.flag_anomalies(results, {"z_threshold": 2.0, "hard_thresholds": {}}, {})

    assert flagged == []


def test_genuine_variation_still_computes_normal_z_score():
    dates = pd.date_range("2026-01-01", periods=95, freq="D")
    rows = [(d.strftime("%Y-%m-%d"), "BTC", "close_price", 100 + i * 0.01, "test") for i, d in enumerate(dates[:-1])]
    rows.append((dates[-1].strftime("%Y-%m-%d"), "BTC", "close_price", 500, "test"))
    history = pd.DataFrame(rows, columns=["date", "asset", "factor", "value", "source"])
    target_date = history["date"].iloc[-1]

    results = anomaly.compute_z_scores(history, target_date, {"window_days": 90, "min_window_days": 30})

    assert len(results) == 1
    r = results[0]
    assert r["status"] == "ok"
    assert r["z"] is not None
    assert r["z"] > 2.0
