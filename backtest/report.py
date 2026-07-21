"""把 backtest/output/ 里的结果拼成一份 HTML 报告：每币 IC 表 + 分档柱状图 +
三组权益曲线叠加图 + 绩效表。

分组标准：按 IC(7日) 的符号分"预测方向为正"/"预测方向为负或存疑"两组，不
是按覆盖率——覆盖率均值在多年回测里被早期历史（那时候 funding_rate/OI/
CryptoQuant/DVOL 这些浅历史因子还没有任何数据）系统性拉低，6 个币的均值
全部低于 core.alert.LOW_COVERAGE_THRESHOLD(50%)，按覆盖率分组会把所有币
分进同一组、失去区分度。IC 符号才是这次回测真正查出来的、有决策意义的
分界线：BTC/ETH/SOL 的 7 日 IC 是正的且部分显著，UNI/LINK/LTC 是负的——
分数越高、未来反而跌得越多，这三个币的评分不能用于择时。
"""

import base64
import io
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = Path("backtest/output")
GROUP_LABELS = {"A": "纯翻转", "B": "纯分档", "C": "合并"}
# B/C 数学上恒等（见模块顶部说明），画图时把 C 叠成虚线，视觉上直接印证"完全重叠"
GROUP_STYLE = {
    "A": {"color": "#c1502e", "linestyle": "-", "linewidth": 1.4, "alpha": 1.0},
    "B": {"color": "#34507e", "linestyle": "-", "linewidth": 1.6, "alpha": 1.0},
    "C": {"color": "#1e8a72", "linestyle": (0, (4, 2)), "linewidth": 1.2, "alpha": 0.9},
}
COLOR_GOOD = "#1e8a72"
COLOR_BAD = "#c1502e"
COLOR_MUTED_GRID = "#c7cdd6"


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style_axes(ax):
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(COLOR_MUTED_GRID)
    ax.tick_params(colors="#4a5261")
    ax.grid(axis="y", color=COLOR_MUTED_GRID, linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)


def _equity_chart(asset: str) -> str:
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for group in ["A", "B", "C"]:
        path = OUTPUT_DIR / f"equity_{asset}_{group}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        style = GROUP_STYLE[group]
        ax.plot(
            pd.to_datetime(df.index), df["equity"], label=f"{group} {GROUP_LABELS[group]}",
            color=style["color"], linestyle=style["linestyle"], linewidth=style["linewidth"], alpha=style["alpha"],
        )
    ax.axhline(1.0, color=COLOR_MUTED_GRID, linewidth=0.7, linestyle=":")
    ax.set_title(f"{asset} 三组权益曲线", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.tick_params(labelsize=8)
    _style_axes(ax)
    fig.autofmt_xdate()
    return _fig_to_base64(fig)


def _monotonicity_chart(asset: str, mono_data: dict, horizon: str = "7") -> str:
    table = mono_data.get(horizon, [])
    if not table:
        return ""
    labels = [row["action"] for row in table]
    means = [row.get("mean") for row in table]
    fig, ax = plt.subplots(figsize=(6, 2.8))
    colors = [COLOR_GOOD if (m or 0) >= 0 else COLOR_BAD for m in means]
    ax.bar(range(len(labels)), [m if m is not None else 0 for m in means], color=colors, width=0.6)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7, rotation=20, ha="right")
    ax.axhline(0, color="#4a5261", linewidth=0.7)
    ax.set_title(f"{asset} 分档 vs 未来{horizon}日平均收益", fontsize=11, fontweight="bold")
    ax.tick_params(labelsize=7)
    _style_axes(ax)
    return _fig_to_base64(fig)


def _num(text) -> str:
    return f"<span class='num'>{text}</span>"


def _ic_table_html(ic_results: dict) -> str:
    rows = []
    for h in ["3", "7", "14"]:
        r = ic_results.get(h, {})
        def fmt(v, pct=False):
            if v is None:
                return "N/A"
            return f"{v*100:.1f}%" if pct else f"{v:.3f}"
        rows.append(
            f"<tr><td>{h}日</td><td>{_num(fmt(r.get('ic')))}</td><td>{_num(fmt(r.get('t_stat')))}</td>"
            f"<td>{_num(fmt(r.get('win_rate'), pct=True))}</td><td>{_num(r.get('n', 'N/A'))}</td></tr>"
        )
    return (
        "<table class='data-table'><thead><tr><th>周期</th><th>Rank IC</th><th>t值</th>"
        "<th>胜率</th><th>样本数</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _perf_table_html(group_performance: dict) -> str:
    rows = []
    for group in ["A", "B", "C"]:
        p = group_performance.get(group, {})
        def fmt(v, pct=False):
            if v is None:
                return "N/A"
            return f"{v*100:.1f}%" if pct else f"{v:.2f}"
        rows.append(
            f"<tr><td>{group} {GROUP_LABELS[group]}</td>"
            f"<td>{_num(fmt(p.get('annualized_return'), pct=True))}</td>"
            f"<td>{_num(fmt(p.get('max_drawdown'), pct=True))}</td>"
            f"<td>{_num(fmt(p.get('sharpe')))}</td>"
            f"<td>{_num(fmt(p.get('win_rate'), pct=True))}</td>"
            f"<td>{_num(fmt(p.get('avg_holding_days')))}</td>"
            f"<td>{_num(p.get('trade_count', 'N/A'))}</td>"
            "</tr>"
        )
    return (
        "<table class='data-table'><thead><tr><th>组</th><th>年化收益</th><th>最大回撤</th>"
        "<th>夏普</th><th>胜率</th><th>平均持有天数</th><th>交易次数</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def _asset_section(asset: str, data: dict) -> str:
    coverage = data.get("avg_coverage")
    coverage_str = f"{coverage*100:.0f}%" if coverage is not None else "N/A"
    equity_img = _equity_chart(asset)
    mono_img = _monotonicity_chart(asset, data.get("monotonicity", {}))
    return f"""
<section class="asset-section">
  <h3>{asset} <span class="badge">平均覆盖率 {_num(coverage_str)}</span></h3>
  <div class="row">
    <div class="col table-wrap">{_ic_table_html(data.get('ic_results', {}))}</div>
    <div class="col table-wrap">{_perf_table_html(data.get('group_performance', {}))}</div>
  </div>
  <div class="row">
    <div class="col chart-col"><img src="data:image/png;base64,{equity_img}" alt="{asset} 权益曲线" /></div>
    <div class="col chart-col">{f'<img src="data:image/png;base64,{mono_img}" alt="{asset} 分档收益" />' if mono_img else ''}</div>
  </div>
</section>
"""


def _overview_row(asset: str, data: dict) -> str:
    coverage = data.get("avg_coverage")
    ic7 = data["ic_results"].get("7", {})
    ic_val = ic7.get("ic")
    t_val = ic7.get("t_stat")
    is_positive = (ic_val or 0) > 0
    verdict = "有效" if is_positive else "失效/反向"
    pill_class = "pill-good" if is_positive else "pill-bad"
    best_group = max(data["group_performance"].items(), key=lambda kv: (kv[1].get("sharpe") or -999))
    best_sharpe = best_group[1].get("sharpe")
    best_sharpe_str = f"Sharpe {best_sharpe:.2f}" if best_sharpe is not None else "N/A"
    return (
        f"<tr><td>{asset}</td><td>{_num(f'{coverage*100:.0f}%')}</td>"
        f"<td>{_num(f'{ic_val:.3f}')}</td><td>{_num(f'{t_val:.2f}')}</td>"
        f"<td><span class='pill {pill_class}'>{verdict}</span></td>"
        f"<td>{best_group[0]} ({_num(best_sharpe_str)})</td></tr>"
    )


def generate_report(output_path: str = "backtest/output/report.html"):
    with open(OUTPUT_DIR / "summary.json", encoding="utf-8") as f:
        summary = json.load(f)

    meta = summary["meta"]
    assets = summary["assets"]

    positive_assets = {a: d for a, d in assets.items() if (d["ic_results"].get("7", {}).get("ic") or 0) > 0}
    negative_assets = {a: d for a, d in assets.items() if (d["ic_results"].get("7", {}).get("ic") or 0) <= 0}

    overview_rows = "".join(_overview_row(a, d) for a, d in assets.items())
    sections_full = "".join(_asset_section(a, d) for a, d in positive_assets.items())
    sections_low = "".join(_asset_section(a, d) for a, d in negative_assets.items())

    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>六币回测报告</title>
<style>
:root {{
  --bg: #f4f5f7;
  --surface: #ffffff;
  --border: #dde1e7;
  --text: #161922;
  --text-muted: #626a78;
  --accent: #34507e;
  --accent-soft: #e8edf5;
  --good: #1e8a72;
  --good-soft: #e3f3ef;
  --bad: #c1502e;
  --bad-soft: #fbe9e3;
  --warn-bg: #fdf3df;
  --warn-border: #e8c477;
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
  max-width: 1120px; margin: 0 auto; padding: 40px 20px 80px;
  line-height: 1.55;
}}
.num, .num * {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-variant-numeric: tabular-nums; }}

h1 {{ font-size: 24px; font-weight: 700; margin: 0 0 6px; text-wrap: balance; }}
h2 {{ font-size: 17px; font-weight: 700; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-top: 44px; }}
h3 {{ font-size: 15px; font-weight: 700; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }}

.meta {{ color: var(--text-muted); font-size: 13px; margin: 0 0 8px; }}

.warning {{
  background: var(--warn-bg); border: 1px solid var(--warn-border);
  padding: 12px 16px; border-radius: 8px; margin: 14px 0;
  font-size: 13.5px; color: var(--text);
}}

.asset-section {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; margin: 16px 0;
}}
.badge {{
  font-size: 11.5px; font-weight: 400; color: var(--text-muted);
  background: var(--accent-soft); padding: 3px 10px; border-radius: 999px;
}}
.pill {{ font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px; }}
.pill-good {{ color: var(--good); background: var(--good-soft); }}
.pill-bad {{ color: var(--bad); background: var(--bad-soft); }}

.row {{ display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; margin-bottom: 14px; }}
.row:last-child {{ margin-bottom: 0; }}
.col {{ flex: 1; min-width: 300px; }}
.chart-col {{ background: var(--surface); border-radius: 8px; overflow: hidden; }}

.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.data-table {{ background: transparent; }}
th, td {{ border-bottom: 1px solid var(--border); padding: 7px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--text-muted); font-weight: 600; font-size: 12px; }}
.overview-table tbody tr:hover {{ background: var(--accent-soft); }}

img {{ max-width: 100%; display: block; }}
</style>
</head><body>
<h1>六币策略回测报告</h1>
<p class="meta">回测区间 {meta['start_date']} ~ {meta['end_date']} · 清仓线 {_num(meta['clear_line'])} · 单边手续费+滑点 {_num(f"{meta['fee_rate']*100:.2f}%")}</p>

<div class="warning">
⚠️ 组B(纯分档)和组C(合并)在当前现货版实现下数学上完全等价：分档表本身在合成分&lt;0.4时就已经把仓位归零，
"信号翻转清仓"这层兜底只在分数已经&lt;清仓线(默认0，落在0.4以下的区间)时触发，而那时分档也已经是0仓位了。
换句话说，"翻转清仓"这个设计在纯现货、不能做空的前提下不会带来任何独立增量——如果要验证它的价值，
必须先支持做空（这样看空/强烈看空档才会有非零仓位，clear_line才有东西可以覆盖）。这不是回测bug，是策略定义本身的数学结果。
</div>

<div class="warning">
⚠️ 覆盖率均值被早期历史拉低：funding_rate/OI/多空比/CryptoQuant/DVOL 这些因子的真实历史都很浅
（几十天到一年多不等），在2018~2025这几年的回测样本里它们基本是缺失状态，把多年平均覆盖率拖到了
30~46%。这不代表"现在"的覆盖率——2026-07-21 那次真实播报里 BTC/ETH/UNI 的覆盖率是 65~72%。
</div>

<h2>总览</h2>
<div class="table-wrap">
<table class="overview-table data-table">
<thead><tr><th>币种</th><th>平均覆盖率</th><th>IC(7日)</th><th>t值</th><th>预测力</th><th>最优组(Sharpe)</th></tr></thead>
<tbody>{overview_rows}</tbody>
</table>
</div>

<h2>预测方向为正的币种（BTC/ETH/SOL）</h2>
<p class="meta">分数越高，未来收益统计上确实倾向更高——评分对这些币有实际参考意义，但仍是弱信号（IC普遍&lt;0.1），不是精确预测。</p>
{sections_full if sections_full else '<p>无</p>'}

<h2>预测方向为负或存疑的币种（UNI/LINK/LTC）</h2>
<p class="meta">IC为负、分档不单调——分数越高未来反而可能跌得更多。这三个币现在的评分不应该用来指导仓位，需要先查是权重/因子选择的问题还是这些币本身跟当前因子集脱钩。</p>
{sections_low if sections_low else '<p>无</p>'}

</body></html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 写入 {output_path}")

    # Artifact 工具会自己套 <!doctype html><head>...</head><body>，不能再传一份
    # 完整 html/head/body 进去，不然是嵌套双层——这里剥掉外层包装，只留
    # title/style/正文，供 Artifact 发布用；report.html 本身仍是完整独立文件。
    inner = html
    inner = inner.replace('<!doctype html>\n<html lang="zh"><head><meta charset="utf-8">\n', "")
    inner = inner.replace("</head><body>", "")
    inner = inner.replace("</body></html>\n", "")
    artifact_path = Path(output_path).with_name("report_artifact.html")
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(inner)
    print(f"[report] 写入 {artifact_path}（Artifact 发布用，无 html/head/body 包装）")

    return output_path


if __name__ == "__main__":
    generate_report()
