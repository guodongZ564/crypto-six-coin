"""三币（BTC/ETH/SOL）叙事日报入口：确定性数据(prepare_report) → Claude
叙事(narrator) → 拼装最终播报。顶部"弱信号·辅助参考"是固定横幅，不让
Claude 有机会把它省略掉——横幅和异动列表都是代码直接拼的，不经过 LLM。
"""

import sys
from datetime import date

from core import alert, store
from narrate import narrator, prepare_report

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WARNING_BANNER = "⚠️弱信号·辅助参考，不是自动下单信号"


def _todays_data_present(target_date: str) -> bool:
    """narration 依赖 run_daily.py 当天真的采集到了 BTC/ETH/SOL 的收盘价——
    这是评分能不能算的最基本前提。检查这个而不是等评分算出一堆 None 才发现，
    省一次没意义的 Claude API 调用，也避免推一条"看着像正常日报、其实全是
    无法评分"的空报。"""
    config = prepare_report.load_config()
    factor_history = store.load(config["data"]["parquet_path"])
    todays_close = factor_history[
        (factor_history["date"] == target_date)
        & (factor_history["factor"] == "close_price")
        & (factor_history["asset"].isin(prepare_report.LIVE_ASSETS))
    ]
    return len(todays_close) >= len(prepare_report.LIVE_ASSETS)


def _format_anomalies(anomalies: list) -> str:
    if not anomalies:
        return ""
    lines = ["", "—— 异动 ——"]
    for a in anomalies:
        z = a.get("z")
        z_text = f"z={z:+.1f}" if z is not None else ""
        direction = f" → {a['direction_text']}" if a.get("direction_text") else ""
        lines.append(f"⚠️ {a['asset']} {a['factor']} {z_text} 当前{alert.format_value(a['value'])}{direction}")
    return "\n".join(lines)


def build_report(target_date: str) -> tuple:
    """返回 (报告文本, payload)，payload 留给调用方存档/调试用。"""
    payload = prepare_report.prepare(target_date)
    narrative = narrator.generate_narrative(payload)

    lines = [f"📊 三币策略日报 · {target_date}", WARNING_BANNER, "", narrative]
    anomaly_section = _format_anomalies(payload["anomalies"])
    if anomaly_section:
        lines.append(anomaly_section)

    return "\n".join(lines), payload


def main():
    target_date = date.today().isoformat()

    if not _todays_data_present(target_date):
        message = f"📊 三币策略日报 · {target_date}\n⚠️ 今日采集数据不完整（BTC/ETH/SOL 收盘价未齐），跳过评分，明天再看。"
        print(message)
        alert.send_telegram_message(message)
        return

    report_text, payload = build_report(target_date)
    print(report_text)
    alert.send_telegram_message(report_text)
    print()
    print("[run_narrated_report] payload 摘要：", {
        c["asset"]: {"score": c["composite_score"], "action": c["action"], "position": c["target_position_pct"]}
        for c in payload["coins"]
    })


if __name__ == "__main__":
    main()
