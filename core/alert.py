"""Telegram 报警：格式化消息 + 直接调 Bot API 发送（不用第三方 SDK）。"""

import os

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


def _format_value(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.3f}"
    return f"{value:.5f}"


def format_alert_message(date_str: str, anomalies: list[dict], summary: dict) -> str:
    lines = [f"📡 因子异动 · {date_str}"]
    for a in anomalies:
        z = a.get("z")
        arrow = "▲" if (z is not None and z > 0) else "▼"
        emoji = "🔴" if (z is None or z > 0) else "🟢"
        z_text = f"{z:+.1f}" if z is not None else "N/A"
        mean_text = _format_value(a["mean"]) if a.get("mean") is not None else "N/A"
        direction_text = a.get("direction_text") or ""
        suffix = f" → {direction_text}" if direction_text else ""
        lines.append(
            f"{emoji} {a['asset']} {a['label']} {arrow} z={z_text}  "
            f"当前{_format_value(a['value'])}（{a['asset']}近90日均{mean_text}）{suffix}"
        )
    lines.append(f"—— 采集{summary['collected']}因子 异动{summary['anomaly_count']} 失败源{summary['failed_sources']}")
    return "\n".join(lines)


def format_no_anomaly_message(date_str: str, summary: dict) -> str:
    return f"✅ 今日无异动 采集{summary['collected']} 失败{summary['failed_sources']}"


def send_telegram_message(text: str, token: str | None = None, chat_id: str | None = None) -> dict:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未配置")

    resp = requests.post(
        f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
