"""轻量级 SVG 折线图生成器：不用 matplotlib、不依赖任何外部 CDN，纯手拼 SVG。

仪表盘要给六币每个因子都画一张历史曲线，少说上百张图——backtest/report.py
那种 matplotlib PNG 一张就要几十KB，图一多页面直接膨胀到几MB不现实。SVG
折线一张也就一两KB，够用。
"""

import html as html_escape


def _format_num(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:.3f}"
    return f"{v:.5f}"


def render_sparkline(dates: list, values: list, width: int = 320, height: int = 80, color: str = "var(--accent)") -> str:
    """dates/values 按时间升序对齐；None 值会被跳过。少于2个有效点时返回"无数据"提示。"""
    pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
    if len(pairs) < 2:
        return "<div class='no-data'>历史数据不足</div>"

    vs = [v for _, v in pairs]
    vmin, vmax = min(vs), max(vs)
    vrange = (vmax - vmin) or (abs(vmax) or 1)

    pad_x, pad_y = 3, 8
    n = len(pairs)
    span_x = width - 2 * pad_x
    span_y = height - 2 * pad_y

    def x_at(i):
        return pad_x + span_x * i / (n - 1)

    def y_at(v):
        return height - pad_y - span_y * (v - vmin) / vrange

    points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_, v) in enumerate(pairs))
    last_date, last_value = pairs[-1]
    first_date = pairs[0][0]

    baseline_y = y_at(0) if vmin <= 0 <= vmax else None
    baseline_svg = (
        f'<line x1="{pad_x}" y1="{baseline_y:.1f}" x2="{width - pad_x}" y2="{baseline_y:.1f}" '
        f'stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2" />'
        if baseline_y is not None else ""
    )

    return f"""<svg viewBox="0 0 {width} {height}" class="sparkline" preserveAspectRatio="none" role="img"
     aria-label="{html_escape.escape(str(last_date))} 最新值 {html_escape.escape(_format_num(last_value))}">
  {baseline_svg}
  <polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" />
  <circle cx="{x_at(n - 1):.1f}" cy="{y_at(last_value):.1f}" r="2.4" fill="{color}" />
</svg>
<div class="spark-meta">
  <span>{html_escape.escape(str(first_date))}</span>
  <span class="spark-latest">{_format_num(last_value)}</span>
  <span>{html_escape.escape(str(last_date))}</span>
</div>"""
