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


DIMENSION_SHORT_LABELS = {
    "技术面": "技术",
    "资金面": "资金",
    "链上/基本面": "链上",
    "衍生品情绪": "衍生",
}

LOW_COVERAGE_THRESHOLD = 0.5


def _format_coin_score_line(result) -> str:
    score_str = f"{result.composite_score:+.2f}" if result.composite_score is not None else "N/A"
    conf_str = f"{result.confidence * 100:.0f}%" if result.confidence is not None else "N/A"
    dim_coverage = " ".join(
        f"{DIMENSION_SHORT_LABELS[d]}{dim.valid_factor_count}/{dim.total_factor_count}"
        for d, dim in result.dimensions.items()
        if dim.total_factor_count > 0  # 0/0 = 规则表里这个维度对该币结构性不适用（比如BTC没有链上/基本面因子），不是数据缺口
    )

    line = (
        f"{result.asset} {score_str} {result.action}"
        f"（置信度{conf_str}，覆盖{result.valid_factor_count}/{result.total_factor_count}：{dim_coverage}）"
    )

    ratio = (result.valid_factor_count / result.total_factor_count) if result.total_factor_count else 0
    warnings = []
    if result.empty_dimensions:
        missing = "、".join(DIMENSION_SHORT_LABELS.get(d, d) for d in result.empty_dimensions)
        warnings.append(f"⚠️缺{missing}维度")
    if ratio < LOW_COVERAGE_THRESHOLD:
        warnings.append("⚠️低覆盖，仅供参考")
    if warnings:
        line += "\n   " + " ".join(warnings)

    return line


UNBACKTESTED_WARNING = "⚠️评分逻辑尚未回测验证，参考非交易建议"


def format_score_broadcast(target_date: str, regime, coin_results: dict, asset_order: list) -> str:
    lines = [f"📊 六币评分 · {target_date}", UNBACKTESTED_WARNING]

    if regime.regime_score > 0.3:
        regime_dir = "偏多"
    elif regime.regime_score < -0.3:
        regime_dir = "偏空"
    else:
        regime_dir = "中性"
    macro_cov = f"宏观{regime.macro_dimension.valid_factor_count}/{regime.macro_dimension.total_factor_count}"
    cycle_cov = f"周期{regime.cycle_dimension.valid_factor_count}/{regime.cycle_dimension.total_factor_count}"
    lines.append(f"大环境 regime {regime.regime_score:+.2f}（{regime_dir}，覆盖 {macro_cov} {cycle_cov}）")
    lines.append("")

    full_coverage = [a for a in asset_order if not coin_results[a].empty_dimensions]
    partial_coverage = [a for a in asset_order if coin_results[a].empty_dimensions]

    for asset in full_coverage:
        lines.append(_format_coin_score_line(coin_results[asset]))

    if partial_coverage:
        lines.append("")
        lines.append("—— 以下维度不齐，不与上面直接比大小 ——")
        for asset in partial_coverage:
            lines.append(_format_coin_score_line(coin_results[asset]))

    return "\n".join(lines)


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
