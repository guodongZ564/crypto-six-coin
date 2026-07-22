"""生成静态HTML仪表盘（docs/index.html）：可交互数据表——每个因子一行，
今日值+涨跌+异动高亮+可hover查看历史的折线图。BTC/ETH/SOL带评分（放在
因子表下面），UNI/LINK/LTC只展示原始因子(评分已冻结，不显示综合分)。

不接LLM，纯确定性数据展示——跟 narrate/ 的叙事层完全独立，这个页面给人
"看数据"用，不是"看AI解读"用。

展示顺序按"客观在前、主观在后"：每个币卡片里先放因子表，综合分/维度分/
动作放最后。
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
        by_asset.setdefault(a["asset"], {})[a["factor"]] = a
    return by_asset


def _factor_label(factor_name: str, factor_meta: dict) -> str:
    return factor_meta.get(factor_name, {}).get("label", factor_name)


def _compute_change(values: list) -> tuple:
    """取最后两个非None值算涨跌。返回 (今日值, 方向up/down/None, 涨跌幅字符串)。"""
    valid = [v for v in values if v is not None]
    if not valid:
        return None, None, None
    today = valid[-1]
    if len(valid) < 2 or valid[-2] == 0:
        return today, None, None
    yesterday = valid[-2]
    pct = (today - yesterday) / abs(yesterday) * 100
    if pct > 0.001:
        direction = "up"
    elif pct < -0.001:
        direction = "down"
    else:
        direction = None
    return today, direction, f"{pct:+.2f}%"


def _render_factor_row(factor_name: str, dates: list, values: list, factor_meta: dict, factor_anomalies: dict) -> str:
    label = _factor_label(factor_name, factor_meta)
    today_value, direction, change_str = _compute_change(values)
    chart_html = sparkline.render_interactive_chart(dates, values, factor_name)

    anomaly_info = factor_anomalies.get(factor_name)
    row_class = "factor-row"
    z_badge = ""
    if anomaly_info:
        z = anomaly_info.get("z")
        is_up = z is not None and z > 0
        row_class += " anomaly-up" if is_up else " anomaly-down"
        if z is not None:
            z_badge = f"<span class='z-badge'>z={z:+.2f}</span>"

    change_html = f"<span class='factor-change {direction}'>{change_str}</span>" if direction and change_str else ""
    value_str = alert.format_value(today_value) if today_value is not None else "N/A"

    return f"""<div class="{row_class}">
  <div class="factor-label">{label}{z_badge}</div>
  <div class="factor-value">{value_str}{change_html}</div>
  <div class="factor-chart">{chart_html}</div>
</div>"""


def _render_factor_table(factor_series: dict, factor_meta: dict, factor_anomalies: dict) -> str:
    rows = "".join(_render_factor_row(name, d, v, factor_meta, factor_anomalies) for name, (d, v) in factor_series.items())
    return f'<div class="factor-table">{rows}</div>'


def _render_score_panel(coin_payload: dict) -> str:
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
"""


def _render_scored_coin(asset: str, factor_series: dict, coin_payload: dict, factor_anomalies: dict, factor_meta: dict) -> str:
    return f"""
<section class="coin-card">
  <h2>{asset}</h2>
  <h3>因子</h3>
  {_render_factor_table(factor_series, factor_meta, factor_anomalies)}
  {_render_score_panel(coin_payload)}
</section>
"""


def _render_frozen_coin(asset: str, factor_series: dict, factor_anomalies: dict, factor_meta: dict) -> str:
    return f"""
<section class="coin-card">
  <h2>{asset} <span class="badge badge-frozen">评分不可用</span></h2>
  <h3>因子</h3>
  {_render_factor_table(factor_series, factor_meta, factor_anomalies)}
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


HOVER_SCRIPT = """
<script>
(function () {
  function formatNum(v) {
    if (Math.abs(v) >= 1000) return v.toLocaleString('en-US', {maximumFractionDigits: 0});
    if (Math.abs(v) >= 1) return v.toFixed(3);
    return v.toFixed(5);
  }

  document.querySelectorAll('.chart-wrap').forEach(function (wrap) {
    var svg = wrap.querySelector('.chart-svg');
    var dataEl = wrap.querySelector('.chart-data');
    if (!svg || !dataEl) return;
    var points = JSON.parse(dataEl.textContent);
    var tooltip = wrap.querySelector('.chart-tooltip');
    var hoverLine = wrap.querySelector('.hover-line');
    var hoverDot = wrap.querySelector('.hover-dot');
    var vb = svg.viewBox.baseVal;
    var pad = 3;
    var n = points.length;
    var vs = points.map(function (p) { return p[1]; });
    var vmin = Math.min.apply(null, vs), vmax = Math.max.apply(null, vs);
    var vrange = (vmax - vmin) || (Math.abs(vmax) || 1);

    function xAt(i) { return pad + (vb.width - 2 * pad) * i / (n - 1); }
    function yAt(v) { return vb.height - pad - (vb.height - 2 * pad) * (v - vmin) / vrange; }

    function handleMove(clientX) {
      var rect = svg.getBoundingClientRect();
      var relX = (clientX - rect.left) / rect.width;
      var idx = Math.max(0, Math.min(n - 1, Math.round(relX * (n - 1))));
      var point = points[idx];
      var svgX = xAt(idx), svgY = yAt(point[1]);

      hoverLine.setAttribute('x1', svgX);
      hoverLine.setAttribute('x2', svgX);
      hoverLine.style.display = 'block';
      hoverDot.setAttribute('cx', svgX);
      hoverDot.setAttribute('cy', svgY);
      hoverDot.style.display = 'block';

      tooltip.textContent = point[0] + '：' + formatNum(point[1]);
      tooltip.style.display = 'block';
      var pxX = (svgX / vb.width) * rect.width;
      tooltip.style.left = Math.max(0, Math.min(pxX, rect.width - 90)) + 'px';
    }

    function handleLeave() {
      hoverLine.style.display = 'none';
      hoverDot.style.display = 'none';
      tooltip.style.display = 'none';
    }

    svg.addEventListener('mousemove', function (e) { handleMove(e.clientX); });
    svg.addEventListener('mouseleave', handleLeave);
    svg.addEventListener('touchmove', function (e) {
      handleMove(e.touches[0].clientX);
      e.preventDefault();
    }, { passive: false });
    svg.addEventListener('touchend', handleLeave);
  });
})();
</script>
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
  max-width: 1100px; margin: 0 auto; padding: 32px 20px 80px;
  line-height: 1.55;
}}
.num, .num * {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-variant-numeric: tabular-nums; }}
h1 {{ font-size: 22px; font-weight: 700; margin: 0 0 6px; }}
h2 {{ font-size: 18px; font-weight: 700; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }}
h3 {{ font-size: 12.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin: 18px 0 8px; }}
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

.factor-table {{ display: flex; flex-direction: column; gap: 3px; }}
.factor-row {{
  display: grid; grid-template-columns: 150px 150px 1fr; align-items: center; gap: 14px;
  padding: 7px 10px 7px 9px; border-radius: 6px; border-left: 3px solid transparent;
}}
.factor-row.anomaly-up {{ border-left-color: var(--bad); background: var(--bad-soft); }}
.factor-row.anomaly-down {{ border-left-color: var(--good); background: var(--good-soft); }}
.factor-label {{ font-size: 12.5px; font-weight: 600; display: flex; align-items: center; gap: 6px; }}
.z-badge {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 999px; background: rgba(127,127,127,0.18); }}
.factor-value {{
  font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-variant-numeric: tabular-nums;
  font-size: 17px; font-weight: 700; display: flex; align-items: baseline; gap: 8px; white-space: nowrap;
}}
.factor-change {{ font-size: 11px; font-weight: 600; font-family: inherit; }}
.factor-change.up {{ color: var(--bad); }}
.factor-change.down {{ color: var(--good); }}

.chart-wrap {{ position: relative; height: 44px; }}
.chart-svg {{ width: 100%; height: 100%; display: block; cursor: crosshair; }}
.hover-line {{ stroke: var(--text-muted); stroke-width: 1; display: none; }}
.hover-dot {{ fill: var(--accent); display: none; }}
.chart-tooltip {{
  position: absolute; top: 0; transform: translateY(-100%);
  background: var(--text); color: var(--bg); font-size: 11px; padding: 3px 7px; border-radius: 4px;
  white-space: nowrap; pointer-events: none; display: none; z-index: 10;
}}
.no-data {{ color: var(--text-muted); font-size: 12px; font-style: italic; }}

.table-wrap {{ overflow-x: auto; margin: 10px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border-bottom: 1px solid var(--border); padding: 6px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--text-muted); font-weight: 600; font-size: 12px; }}
.credibility-note {{ font-size: 12.5px; color: var(--text-muted); margin-top: 10px; }}
.frozen-note {{ font-size: 13px; color: var(--text-muted); margin-top: 10px; }}
</style>
</head><body>
<h1>六币因子仪表盘</h1>
<p class="meta">数据日期 {target_date}</p>
<div class="disclaimer">⚠️ {DISCLAIMER}</div>

{regime_html}
{body}

{HOVER_SCRIPT}
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
            asset, factor_series, coin_score_by_asset[asset], anomalies_by_asset.get(asset, {}), factor_meta,
        ))
    for asset in FROZEN_ASSETS:
        factor_series = _factor_series_by_asset(history, asset)
        sections.append(_render_frozen_coin(asset, factor_series, anomalies_by_asset.get(asset, {}), factor_meta))

    regime_html = _render_regime(payload["regime"])
    html = _assemble_page(target_date, regime_html, sections)

    out_path = Path(OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[dashboard] 写入 {out_path}（{len(html)} 字符）")


if __name__ == "__main__":
    build()
