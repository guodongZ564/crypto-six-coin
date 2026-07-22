"""交互式 SVG 折线图：hover 时显示对应日期和数值的 tooltip。纯手写 SVG+原生
JS，不接任何外部图表库/CDN——六币加起来上百个因子，接一个通用图表库反而
增加不必要的体积和"库挂了页面就崩"的风险，原生实现更可控、离线也能跑。

历史数据点太多(比如BTC收盘价有3000+天)时先降采样到 MAX_POINTS 个点再画，
这么小的图本来也显示不出每天的细节，降采样不影响观感，还能把要塞进页面的
JSON 体积压下来。hover 交互的 JS 逻辑统一写在 build_dashboard.py 里一次性
注入页面（事件委托到所有图表上），不是每张图重复一份脚本。
"""

import json

MAX_POINTS = 200


def _downsample(dates: list, values: list, max_points: int = MAX_POINTS) -> list:
    pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
    if len(pairs) <= max_points:
        return pairs
    step = (len(pairs) - 1) / (max_points - 1)
    indices = sorted({round(i * step) for i in range(max_points)} | {0, len(pairs) - 1})
    return [pairs[i] for i in indices]


def render_interactive_chart(dates: list, values: list, chart_id: str, width: int = 220, height: int = 44, color: str = "var(--accent)") -> str:
    """返回一段 <div class='chart-wrap'>...</div>，需要配合 build_dashboard.py
    页面里统一注入的 hover 脚本（读取内嵌的 <script type="application/json"> 数据）。
    """
    pairs = _downsample(dates, values)
    if len(pairs) < 2:
        return "<div class='no-data'>历史数据不足</div>"

    vs = [v for _, v in pairs]
    vmin, vmax = min(vs), max(vs)
    vrange = (vmax - vmin) or (abs(vmax) or 1)

    pad = 3
    n = len(pairs)
    span_x = width - 2 * pad
    span_y = height - 2 * pad

    def x_at(i):
        return pad + span_x * i / (n - 1)

    def y_at(v):
        return height - pad - span_y * (v - vmin) / vrange

    points_str = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_, v) in enumerate(pairs))
    data_json = json.dumps(pairs, ensure_ascii=False)

    return f"""<div class="chart-wrap">
  <svg viewBox="0 0 {width} {height}" class="chart-svg" preserveAspectRatio="none">
    <polyline points="{points_str}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round" />
    <line class="hover-line" x1="0" y1="0" x2="0" y2="{height}"></line>
    <circle class="hover-dot" r="2.6"></circle>
  </svg>
  <div class="chart-tooltip"></div>
  <script type="application/json" class="chart-data">{data_json}</script>
</div>"""
