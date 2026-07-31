"""叙事日报入口的降级保证：Anthropic API 失败时 build_report 不能把异常
往上抛——那样 main() 崩溃、GitHub Actions 在这一步停住，后面留痕/仪表盘/
数据提交全部被跳过。这里钉死"叙事失败必须降级成原始数据播报，报告正常
生成、正常发出，流程能往下走"。
"""

from narrate import narrator, run_narrated_report


def _fake_payload():
    return {
        "date": "2026-07-31",
        "regime": {
            "regime_score": 0.3, "band_label": "中性偏多",
            "macro_valid": 3, "macro_total": 4,
            "cycle_valid": 2, "cycle_total": 2,
        },
        "coins": [
            {
                "asset": "BTC", "composite_score": 0.42, "action": "轻仓看多",
                "target_position_pct": 20.0, "confidence_pct": 60.0,
                "valid_factor_count": 10, "total_factor_count": 12,
                "dimensions": {
                    "技术": {"score": 0.5, "valid": 3, "total": 3},
                    "资金": {"score": None, "valid": 0, "total": 2},
                },
                "degraded_factors": [],
                "backtest_credibility": {"tier": "弱-仅方向参考", "note": "B组年化仅1.4%，择时优势薄"},
            },
        ],
        "anomalies": [],
        "dynamic_bands": {"threshold_70": 0.5, "threshold_90": 0.9},
    }


def test_build_report_falls_back_when_narration_unavailable(monkeypatch):
    monkeypatch.setattr(run_narrated_report.prepare_report, "prepare", lambda target_date: _fake_payload())

    def _raise(*args, **kwargs):
        raise narrator.NarrationUnavailable("workspace usage limit reached")

    monkeypatch.setattr(run_narrated_report.narrator, "generate_narrative", _raise)

    report_text, payload = run_narrated_report.build_report("2026-07-31")

    assert "叙事生成暂时不可用" in report_text
    assert run_narrated_report.WARNING_BANNER in report_text
    assert "BTC" in report_text
    assert "轻仓看多" in report_text
    assert payload["coins"][0]["asset"] == "BTC"


def test_build_report_uses_real_narrative_when_available(monkeypatch):
    monkeypatch.setattr(run_narrated_report.prepare_report, "prepare", lambda target_date: _fake_payload())
    monkeypatch.setattr(run_narrated_report.narrator, "generate_narrative", lambda payload: "这是真实生成的叙事正文")

    report_text, _ = run_narrated_report.build_report("2026-07-31")

    assert "这是真实生成的叙事正文" in report_text
    assert "叙事生成暂时不可用" not in report_text
