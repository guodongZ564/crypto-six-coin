"""生成静态HTML仪表盘（docs/index.html）：BTC/ETH/SOL带评分，UNI/LINK/LTC
只展示原始因子(评分已冻结，不显示综合分)。不接LLM，纯确定性数据展示——跟
narrate/ 的叙事层完全独立，这个页面给人"看数据"用，不是"看AI解读"用。

展示顺序按"客观在前、主观在后"：每个币卡片里先放因子历史曲线+当日异动，
综合分/维度分/动作放最后。

先只生成本地文件，不接 GitHub Pages 部署——workflow 里只跑生成，不做
deploy 那一步，等用户确认展示逻辑和免责措辞没问题再说。
"""

import sys
from datetime import date
from pathlib import Path

from core import alert, anomaly, store
from dashboard import sparkline
from narrate import prepare_report

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_PATH = "docs/index.html"

SCORED_ASSETS = prepare_report.LIVE_ASSETS  # BTC/ETH/SOL
FROZEN_ASSETS = ["UNI", "LINK", "LTC"]

DISCLAIMER = "本页数据仅供研究参考，非投资建议，不构成任何买卖要约，据此操作风险自负。评分为弱信号且未经实盘验证。"


def _factor_series_by_asset(history, asset: str) -> dict:
    sub = history[history["asset"] == asset]
    result = {}
    for factor_name, group in sub.groupby("factor"):
        g = group.sort_values("date")
        result[factor_name] = (g["date"].tolist(), g["value"].tolist())
    return dict(sorted(result.items()))


def _anomalies_by_asset(history, target_date: str, anomaly_cfg: dict, factor_meta: dict) -> dict:
    z_results = anomaly.compute_z_scores(history, target_date, anomaly_cfg)
    flagged = anomaly.flag_anomalies(z_results, anomaly_cfg, factor_meta)
    by_asset = {}
    for a in flagged:
        by_asset.setdefault(a["asset"], []).append(a)
    return by_asset


def _factor_label(factor_name: str, factor_meta: dict) -> str:
    return factor_meta.get(factor_name, {}).get("label", factor_name)


def _render_anomaly_list(anomalies: list) -> str:
    if not anomalies:
        return "<p class='no-data'>今日无异动</p>"
    items = []
    for a in anomalies:
        z = a.get("z")
        z_text = f"z={z:+.2f}" if z is not None else ""
        direction = f" → {a['direction_text']}" if a.get("direction_text") else ""
        items.append(
            f"<li><span class='anomaly-tag'>⚠️</span> {a['label']} {z_text} "
            f"当前{alert.format_value(a['value'])}{direction}</li>"
        )
    return "<ul class='anomaly-list'>" + "".join(items) + "</ul>"


def _render_factor_charts(asset: str, factor_series: dict, factor_meta: dict) -> str:
    cards = []
    for factor_name, (dates, values) in factor_series.items():
        label = _factor_label(factor_name, factor_meta)
        chart = sparkline.render_sparkline(dates, values)
        cards.append(f"<div class='factor-card'><h4>{label}</h4>{chart}</div>")
    return "<div class='factor-grid'>" + "".join(cards) + "</div>"


def _render_scored_coin(asset: str, factor_series: dict, coin_payload: dict, anomalies: list, factor_meta: dict) -> str:
    dims = coin_payload["dimensions"]
    dim_rows = "".join(
        f"<tr><td>{name}</td><td class='num'>{('%.3f' % d['score']) if d['score'] is not None else 'N/A'}</td>"
        f"<td class='num'>{d['valid']}/{d['total']}</td></tr>"
        for name, d in dims.items() if d["total"] > 0
    )
    composite = coin_payload["composite_score"]
    composite_str = f"{composite:+.3f}" if composite is not None else "N/A"
    conf = coin_payload["confidence_pct"]
    conf_str = f"{conf:.0f}%" if conf is not None else "N/A"
    credibility = coin_payload["backtest_credibility"]

    return f"""
<section class="coin-card">
  <h2>{asset}</h2>

  <h3>因子历史</h3>
  {_render_factor_charts(asset, factor_series, factor_meta)}

  <h3>当日异动</h3>
  {_render_anomaly_list(anomalies)}

  <h3>评分与动作</h3>
  <div class="score-panel">
    <div class="score-summary">
      <span class="big-num">{composite_str}</span>
      <span class="pill">{coin_payload['action']}</span>
      <span class="badge">目标仓位 {coin_payload['target_position_pct']:.0f}%</span>
      <span class="badge">置信度 {conf_str}</span>
      <span class="badge">覆盖 {coin_payload['valid_factor_count']}/{coin_payload['total_factor_count']}</span>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>维度</th><th>分数</th><th>覆盖</th></tr></thead>
        <tbody>{dim_rows}</tbody>
      </table>
    </div>
    <p class="credibility-note">回测可信度：<strong>{credibility['tier']}</strong> — {credibility['note']}</p>
  </div>
</section>
"""


def _render_frozen_coin(asset: str, factor_series: dict, anomalies: list, factor_meta: dict) -> str:
    return f"""
<section class="coin-card">
  <h2>{asset} <span class="badge badge-frozen">评分不可用</span></h2>

  <h3>因子历史</h3>
  {_render_factor_charts(asset, factor_series, factor_meta)}

  <h3>当日异动</h3>
  {_render_anomaly_list(anomalies)}

  <p class="frozen-note">该币种回测显示合成分与未来收益负相关（评分方向与实际走势相反），
  已停用评分，仅保留原始因子数据采集用于后续观察。</p>
</section>
"""


def _render_regime(regime: dict) -> str:
    return f"""
<section class="regime-card">
  <h2>大环境 Regime</h2>
  <div class="score-summary">
    <span class="big-num">{regime['regime_score']:+.3f}</span>
    <span class="pill">{regime['band_label']}</span>
    <span class="badge">宏观覆盖 {regime['macro_valid']}/{regime['macro_total']}</span>
    <span class="badge">行业周期覆盖 {regime['cycle_valid']}/{regime['cycle_total']}</span>
  </div>
</section>
"""


def _assemble_page(target_date: str, regime_html: str, sections: list) -> str:
    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>六币因子仪表盘 · {target_date}</title>
<style>
:root {{
  --bg: #f4f5f7; --surface: #ffffff; --border: #dde1e7;
  --text: #161922; --text-muted: #626a78;
  --accent: #34507e; --accent-soft: #e8edf5;
  --good: #1e8a72; --good-soft: #e3f3ef;
  --bad: #c1502e; --bad-soft: #fbe9e3;
  --warn-bg: #fdf3df; --warn-border: #e8c477;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #10131a; --surface: #1a1e27; --border: #2b303c;
    --text: #e8eaf0; --text-muted: #97a0b3;
    --accent: #8fa8d6; --accent-soft: #202a3d;
    --good: #4fbfa0; --good-soft: #163330;
    --bad: #e2825f; --bad-soft: #3a2320;
    --warn-bg: #33291a; --warn-border: #6b5326;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #10131a; --surface: #1a1e27; --border: #2b303c;
  --text: #e8eaf0; --text-muted: #97a0b3;
  --accent: #8fa8d6; --accent-soft: #202a3d;
  --good: #4fbfa0; --good-soft: #163330;
  --bad: #e2825f; --bad-soft: #3a2320;
  --warn-bg: #33291a; --warn-border: #6b5326;
}}
:root[data-theme="light"] {{
  --bg: #f4f5f7; --surface: #ffffff; --border: #dde1e7;
  --text: #161922; --text-muted: #626a78;
  --accent: #34507e; --accent-soft: #e8edf5;
  --good: #1e8a72; --good-soft: #e3f3ef;
  --bad: #c1502e; --bad-soft: #fbe9e3;
  --warn-bg: #fdf3df; --warn-border: #e8c477;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: "Microsoft YaHei", -apple-system, "Segoe UI", "PingFang SC", sans-serif;
  background: var(--bg); color: var(--text);
  max-width: 1200px; margin: 0 auto; padding: 32px 20px 80px;
  line-height: 1.55;
}}
.num, .num * {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-variant-numeric: tabular-nums; }}
h1 {{ font-size: 22px; font-weight: 700; margin: 0 0 6px; }}
h2 {{ font-size: 18px; font-weight: 700; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }}
h3 {{ font-size: 13px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin: 20px 0 10px; }}
.meta {{ color: var(--text-muted); font-size: 13px; }}
.disclaimer {{
  background: var(--warn-bg); border: 1px solid var(--warn-border);
  padding: 14px 18px; border-radius: 8px; margin: 16px 0 24px; font-size: 13.5px; font-weight: 600;
}}
.regime-card, .coin-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 20px 22px; margin: 18px 0;
}}
.score-summary {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 10px; }}
.big-num {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-size: 26px; font-weight: 700; }}
.pill {{ font-size: 13px; font-weight: 700; padding: 4px 12px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }}
.badge {{ font-size: 12px; color: var(--text-muted); background: var(--accent-soft); padding: 3px 10px; border-radius: 999px; }}
.badge-frozen {{ background: var(--bad-soft); color: var(--bad); font-weight: 700; }}
.factor-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
.factor-card {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; background: var(--bg); }}
.factor-card h4 {{ font-size: 12px; font-weight: 700; margin: 0 0 6px; color: var(--text); }}
.sparkline {{ width: 100%; height: 60px; display: block; }}
.spark-meta {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); margin-top: 2px; }}
.spark-latest {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; color: var(--text); font-weight: 700; }}
.no-data {{ color: var(--text-muted); font-size: 12px; font-style: italic; }}
.anomaly-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }}
.anomaly-list li {{ font-size: 13px; background: var(--bad-soft); color: var(--text); padding: 6px 10px; border-radius: 6px; }}
.anomaly-tag {{ margin-right: 4px; }}
.table-wrap {{ overflow-x: auto; margin: 10px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border-bottom: 1px solid var(--border); padding: 6px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--text-muted); font-weight: 600; font-size: 12px; }}
.credibility-note {{ font-size: 12.5px; color: var(--text-muted); margin-top: 10px; }}
.frozen-note {{ font-size: 13px; color: var(--text-muted); margin-top: 6px; }}
</style>
</head><body>
<h1>六币因子仪表盘</h1>
<p class="meta">数据日期 {target_date}</p>
<div class="disclaimer">⚠️ {DISCLAIMER}</div>

{regime_html}
{body}
</body></html>
"""


def build():
    config = prepare_report.load_config()
    target_date = date.today().isoformat()
    history = store.load(config["data"]["parquet_path"])

    payload = prepare_report.prepare(target_date)
    coin_score_by_asset = {c["asset"]: c for c in payload["coins"]}

    anomaly_cfg = config["anomaly"]
    factor_meta = config.get("factor_meta", {})
    anomalies_by_asset = _anomalies_by_asset(history, target_date, anomaly_cfg, factor_meta)

    sections = []
    for asset in SCORED_ASSETS:
        factor_series = _factor_series_by_asset(history, asset)
        sections.append(_render_scored_coin(
            asset, factor_series, coin_score_by_asset[asset], anomalies_by_asset.get(asset, []), factor_meta,
        ))
    for asset in FROZEN_ASSETS:
        factor_series = _factor_series_by_asset(history, asset)
        sections.append(_render_frozen_coin(asset, factor_series, anomalies_by_asset.get(asset, []), factor_meta))

    regime_html = _render_regime(payload["regime"])
    html = _assemble_page(target_date, regime_html, sections)

    out_path = Path(OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[dashboard] 写入 {out_path}（{sum(len(s) for s in sections)} 字符正文）")


if __name__ == "__main__":
    build()
