"""评分实盘验证报告：docs/tracking.html。跟 dashboard(看"今天")是两回事——
这个看"评分到底准不准"，用 data/scoring_track.parquet 里记录当时的真实分数
+后来真实发生的价格做事后检验，不是回测的历史重演。

分档检验(高/中/低三档，按综合分分位数切)+实盘IC，只用"已经满期"的记录
（对应horizon的未来收益列不是None的那些），未满期的记录不参与统计——不能
拿还没到期的记录凑样本量。
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

from tracking import record_track

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_PATH = "docs/tracking.html"
MIN_SAMPLE_SIZE = 60
HORIZONS = record_track.HORIZONS

# 跟规格3回测报告里同一批真实数字对齐，供实盘IC对比参考
BACKTEST_IC_7D = {"BTC": 0.038, "ETH": 0.041, "SOL": 0.091}


def _bucket_test(asset_df: pd.DataFrame, horizon: int):
    pct_col = f"fwd_{horizon}d_pct"
    mature = asset_df.dropna(subset=["composite_score", pct_col])
    if len(mature) < 3:
        return None, len(mature)

    mature = mature.copy()
    try:
        mature["bucket"] = pd.qcut(mature["composite_score"], q=3, labels=["低", "中", "高"], duplicates="drop")
    except ValueError:
        return None, len(mature)

    grouped = mature.groupby("bucket", observed=True)[pct_col].agg(["mean", "count"])
    return grouped, len(mature)


def _live_ic(asset_df: pd.DataFrame, horizon: int):
    pct_col = f"fwd_{horizon}d_pct"
    mature = asset_df.dropna(subset=["composite_score", pct_col])
    if len(mature) < 10:
        return None, len(mature)
    ic = mature["composite_score"].corr(mature[pct_col], method="spearman")
    if ic is None or pd.isna(ic):
        return None, len(mature)
    return float(ic), len(mature)


def _bucket_table_html(bucket_result, n: int) -> str:
    if bucket_result is None:
        return f"<p class='no-data'>样本不足({n}条)，还算不出分档结果</p>"

    order = ["高", "中", "低"]
    rows = []
    means = {}
    for label in order:
        if label not in bucket_result.index:
            continue
        mean_v = bucket_result.loc[label, "mean"]
        count_v = int(bucket_result.loc[label, "count"])
        means[label] = mean_v
        rows.append(f"<tr><td>{label}分组</td><td class='num'>{mean_v:+.2f}%</td><td class='num'>{count_v}</td></tr>")

    monotonic = None
    if "高" in means and "低" in means:
        monotonic = means["高"] > means["低"]

    verdict = ""
    if monotonic is not None:
        pill_class = "pill-good" if monotonic else "pill-bad"
        verdict_text = "高分组收益 > 低分组，符合预期" if monotonic else "高分组收益 ≤ 低分组，不符合预期"
        verdict = f"<p><span class='pill {pill_class}'>{verdict_text}</span></p>"

    return f"""
<div class="table-wrap">
<table class="data-table">
<thead><tr><th>分组</th><th>平均收益</th><th>样本数</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
{verdict}
"""


def _asset_section(asset: str, asset_df: pd.DataFrame) -> str:
    horizon_blocks = []
    for h in HORIZONS:
        bucket_result, n_bucket = _bucket_test(asset_df, h)
        ic, n_ic = _live_ic(asset_df, h)

        ic_str = f"{ic:+.3f}" if ic is not None else "N/A（样本不足）"
        backtest_ic = BACKTEST_IC_7D.get(asset) if h == 7 else None
        backtest_note = f"（回测同期IC: {backtest_ic:+.3f}）" if backtest_ic is not None else ""

        sample_warning = "" if n_ic >= MIN_SAMPLE_SIZE else f"<span class='badge badge-warn'>样本仅{n_ic}条，未达{MIN_SAMPLE_SIZE}条参考线</span>"

        horizon_blocks.append(f"""
<div class="horizon-block">
  <h4>{h}日窗口</h4>
  {_bucket_table_html(bucket_result, n_bucket)}
  <p class="ic-line">实盘 Rank IC：<strong class="num">{ic_str}</strong> {backtest_note} {sample_warning}</p>
</div>
""")

    return f"""
<section class="coin-card">
  <h2>{asset}</h2>
  {"".join(horizon_blocks)}
</section>
"""


def generate(track_path: str = record_track.TRACK_PATH, output_path: str = OUTPUT_PATH):
    track_df = record_track.load_track(track_path)
    target_date = date.today().isoformat()

    sections = []
    for asset in ["BTC", "ETH", "SOL"]:
        asset_df = track_df[track_df["asset"] == asset]
        sections.append(_asset_section(asset, asset_df))

    total_mature_7d = track_df.dropna(subset=["composite_score", "fwd_7d_pct"])
    total_n = len(total_mature_7d)

    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>评分实盘验证 · {target_date}</title>
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
  max-width: 900px; margin: 0 auto; padding: 32px 20px 80px; line-height: 1.55;
}}
.num, .num * {{ font-family: "Cascadia Code", "SF Mono", Consolas, monospace; font-variant-numeric: tabular-nums; }}
h1 {{ font-size: 22px; font-weight: 700; margin: 0 0 6px; }}
h2 {{ font-size: 18px; font-weight: 700; margin: 0 0 12px; }}
h4 {{ font-size: 13px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin: 16px 0 8px; }}
.meta {{ color: var(--text-muted); font-size: 13px; }}
.warning {{
  background: var(--warn-bg); border: 1px solid var(--warn-border);
  padding: 14px 18px; border-radius: 8px; margin: 16px 0 24px; font-size: 13.5px; font-weight: 600;
}}
.coin-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 22px; margin: 18px 0; }}
.horizon-block {{ margin-bottom: 14px; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border-bottom: 1px solid var(--border); padding: 6px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--text-muted); font-weight: 600; font-size: 12px; }}
.pill {{ font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px; }}
.pill-good {{ background: var(--good-soft); color: var(--good); }}
.pill-bad {{ background: var(--bad-soft); color: var(--bad); }}
.badge {{ font-size: 11px; color: var(--text-muted); background: var(--accent-soft); padding: 2px 8px; border-radius: 999px; margin-left: 6px; }}
.badge-warn {{ background: var(--warn-bg); color: #8a6d1f; }}
.ic-line {{ font-size: 13px; margin: 6px 0 0; }}
.no-data {{ color: var(--text-muted); font-size: 12px; font-style: italic; }}
</style>
</head><body>
<h1>评分实盘验证</h1>
<p class="meta">数据日期 {target_date} · 累计记录 {len(track_df)} 条（BTC/ETH/SOL，UNI/LINK/LTC评分已冻结不记录）</p>

<div class="warning">
⚠️ 样本量不足时结论不可信，建议满 {MIN_SAMPLE_SIZE} 条以上再看。当前7日窗口已满期样本共 {total_n} 条。
本页是"事后不可改"的真实记录——每天只追加当天的分数、只回填到期的未来收益，历史行的分数和动作永远不会被重算或修改。
</div>

{"".join(sections)}

</body></html>
"""

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[tracking_report] 写入 {out_path}")


if __name__ == "__main__":
    generate()
