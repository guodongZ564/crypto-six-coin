"""三币（BTC/ETH/SOL）叙事日报入口：确定性数据(prepare_report) → Claude
叙事(narrator) → 拼装最终播报。顶部"弱信号·辅助参考"是固定横幅，不让
Claude 有机会把它省略掉——横幅和异动列表都是代码直接拼的，不经过 LLM。
"""

import sys
from datetime import date

from core import alert
from narrate import narrator, prepare_report

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WARNING_BANNER = "⚠️弱信号·辅助参考，不是自动下单信号"


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
    report_text, payload = build_report(target_date)
    print(report_text)
    print()
    print("[run_narrated_report] payload 摘要：", {
        c["asset"]: {"score": c["composite_score"], "action": c["action"], "position": c["target_position_pct"]}
        for c in payload["coins"]
    })


if __name__ == "__main__":
    main()
