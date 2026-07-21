"""单因子归一化：当日原始值 → 方向分 [-2,+2]。

只对我们实际采集到数据的 ~25 个因子手写了归一化函数（NORMALIZERS 注册表，
key 是 core/rules.py 解析出来的因子名，跟《规则表》「2-打分规则表」的
"因子/指标"列原样一致）。规则表里其余因子（ETF流/Coinglass/ETH质押/L2/
SOL链上细节/LINK细节/LTC细节/宏观预期差类等）没有数据源，不在这个注册表
里——score.py 按"缺失跳过分母"处理，不是这里的错误。

三类归一化模式对应三个通用 helper：
- score_by_thresholds：绝对阈值型，按有序区间查表。
- score_by_trend：趋势型，当日值 vs 截至前一日的滚动均值，防未来函数。
- percentile_rank：分位型，当日值在截至前一日历史分布里的分位，历史不足
  （<min_history）时返回 None，调用方按"历史不足"处理（各因子函数里体现
  为直接返回 None，跳过打分而不是硬编译一个不可靠的分位数）。

DEGRADED_FACTORS：不是"数据缺失"而是"用近似值代替规则表原意"的因子，目前
只有"联邦基金利率/路径"——规则表要 FOMC 点阵前瞻指引，我们只有利率实际值，
用趋势方向近似。播报/回测要能认出这是降级因子。
"""

from dataclasses import dataclass

import pandas as pd

DEGRADED_FACTORS = {"联邦基金利率/路径"}


def build_factor_index(history: pd.DataFrame) -> dict:
    """把长表按 (asset,factor) 分组、按 date 排好序，一次性建好查找表。

    单个 NormalizeContext 实例内部的按需缓存只能省掉"同一个 ctx 被反复调用"
    的重复筛选；回测一天要建 7 个 ctx（regime 1个 + 6币各1个），如果各建各的
    缓存，同一个 (asset,factor) 组合还是会被从头筛好几遍。这个函数在
    core/score.py 的 compute_all_scores 里只调一次，建好的 dict 被当天全部
    7 个 ctx 共享，把"一天筛好几遍"降到"一天筛一遍"——这是让回测能在合理
    时间内跑完全部历史的关键优化，不是可有可无的花活。
    """
    index = {}
    for (asset, factor), group in history.groupby(["asset", "factor"], sort=False):
        index[(asset, factor)] = group.sort_values("date").set_index("date")["value"]
    return index


@dataclass
class NormalizeContext:
    """asset/target_date 之外，传 history（原始长表）或 index（预建好的查找表，
    见 build_factor_index）二选一即可——两条路径最终都落到同一个 factor_series
    接口，各因子函数不用关心调用方给的是哪一种。
    """

    asset: str
    target_date: str
    history: pd.DataFrame | None = None
    index: dict | None = None

    def __post_init__(self):
        if self.index is None:
            history = self.history if self.history is not None else pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])
            self.index = build_factor_index(history)

    def factor_series(self, factor: str, asset: str | None = None) -> pd.Series:
        asset = asset or self.asset
        # 缺省的空 Series 必须给 object(字符串) index，不能用默认的 int64
        # RangeIndex——不然 history_before_today 里拿它跟 target_date(字符串)
        # 比大小会直接 TypeError
        return self.index.get((asset, factor), pd.Series(dtype=float, index=pd.Index([], dtype=object)))

    def today_value(self, factor: str, asset: str | None = None) -> float | None:
        s = self.factor_series(factor, asset)
        if self.target_date not in s.index:
            return None
        return float(s[self.target_date])

    def history_before_today(self, factor: str, asset: str | None = None) -> pd.Series:
        s = self.factor_series(factor, asset)
        return s[s.index < self.target_date]


def score_by_thresholds(value: float, breakpoints: list) -> float:
    """breakpoints: [(upper_exclusive, score), ..., (None, score_else)]，按 upper 升序。"""
    for upper, score in breakpoints:
        if upper is None or value < upper:
            return score
    return breakpoints[-1][1]


def score_by_trend(
    current: float,
    baseline_series: pd.Series,
    window: int = 7,
    up_score: float = 1.0,
    flat_score: float = 0.0,
    down_score: float = -1.0,
    flat_band_pct: float = 0.02,
) -> float | None:
    if baseline_series.empty:
        return None
    baseline = baseline_series.tail(window).mean()
    if baseline == 0 or pd.isna(baseline):
        return None
    change_pct = (current - baseline) / abs(baseline)
    if change_pct > flat_band_pct:
        return up_score
    if change_pct < -flat_band_pct:
        return down_score
    return flat_score


def percentile_rank(current: float, history_series: pd.Series, min_history: int = 30) -> float | None:
    if len(history_series) < min_history:
        return None
    return float((history_series < current).mean())


# ---------- 技术面 ----------

def _score_price_vs_ma(ctx: NormalizeContext, ma_factor: str, magnitude: float) -> float | None:
    price = ctx.today_value("close_price")
    ma = ctx.today_value(ma_factor)
    if price is None or ma is None or ma == 0:
        return None
    return magnitude if price > ma else -magnitude


def score_price_vs_ma50(ctx: NormalizeContext) -> float | None:
    return _score_price_vs_ma(ctx, "ma50", 1.0)


def score_price_vs_ma200(ctx: NormalizeContext) -> float | None:
    return _score_price_vs_ma(ctx, "ma200", 1.5)


def score_ma_cross(ctx: NormalizeContext) -> float | None:
    ma50 = ctx.today_value("ma50")
    ma200 = ctx.today_value("ma200")
    if ma50 is None or ma200 is None:
        return None
    return 1.0 if ma50 > ma200 else -1.0


def score_rsi_daily(ctx: NormalizeContext) -> float | None:
    rsi = ctx.today_value("rsi14")
    if rsi is None:
        return None
    return score_by_thresholds(rsi, [(30, 1.5), (45, 0.5), (55, 0.0), (70, -0.5), (None, -1.5)])


def score_macd_daily(ctx: NormalizeContext) -> float | None:
    """规则表要 MACD 柱状图(MACD线-信号线)，我们只存了 MACD 线本身，没有信号线。
    用线的正负 + 相对昨日是否在扩大近似代替真柱状图，已跟用户确认接受这个近似。"""
    series = ctx.factor_series("macd").sort_index()
    if ctx.target_date not in series.index:
        return None
    idx = series.index.get_loc(ctx.target_date)
    if idx == 0:
        return None
    today = series.iloc[idx]
    yesterday = series.iloc[idx - 1]
    if today > 0 and today >= yesterday:
        return 1.0
    if today < 0 and today <= yesterday:
        return -1.0
    return 0.0


def score_bollinger_position(ctx: NormalizeContext) -> float | None:
    price = ctx.today_value("close_price")
    upper = ctx.today_value("boll_upper")
    lower = ctx.today_value("boll_lower")
    if price is None or upper is None or lower is None or upper == lower:
        return None
    position = (price - lower) / (upper - lower)  # 0=触下轨, 0.5=中轨, 1=触上轨
    score = 1.0 - 2.0 * position
    return max(-1.0, min(1.0, score))


def score_relative_strength(ctx: NormalizeContext) -> float | None:
    if ctx.asset == "BTC":
        return None
    asset_price = ctx.factor_series("close_price", ctx.asset).sort_index()
    btc_price = ctx.factor_series("close_price", "BTC").sort_index()
    common = asset_price.index.intersection(btc_price.index)
    if ctx.target_date not in common:
        return None
    ratio = asset_price[common] / btc_price[common]
    today_ratio = ratio[ctx.target_date]
    baseline_series = ratio[ratio.index < ctx.target_date]
    return score_by_trend(today_ratio, baseline_series, window=7, up_score=1.0, down_score=-1.0)


# ---------- 资金面 ----------

def score_exchange_netflow(ctx: NormalizeContext) -> float | None:
    if ctx.asset not in ("BTC", "ETH"):  # CryptoQuant 只覆盖这两币
        return None
    today = ctx.today_value("exchange_netflow")
    if today is None:
        return None
    hist = ctx.history_before_today("exchange_netflow")
    if len(hist) < 14:
        return None
    mu = hist.tail(30).mean()
    sigma = hist.tail(30).std()
    if sigma == 0 or pd.isna(sigma):
        return None
    z = (today - mu) / sigma
    # netflow 正=流入交易所(利空)，负=流出(利好)
    if z < -1.0:
        return 1.5
    if z < -0.3:
        return 0.5
    if z < 0.3:
        return 0.0
    return -1.0


def score_volume_vs_avg(ctx: NormalizeContext) -> float | None:
    vol_ratio = ctx.today_value("volume_ratio")
    price_series = ctx.factor_series("close_price").sort_index()
    if vol_ratio is None or ctx.target_date not in price_series.index:
        return None
    idx = price_series.index.get_loc(ctx.target_date)
    if idx == 0:
        return None
    price_change = price_series.iloc[idx] - price_series.iloc[idx - 1]
    direction = 1.0 if price_change > 0 else (-1.0 if price_change < 0 else 0.0)
    magnitude = 1.0 if vol_ratio >= 1.0 else 0.5
    return direction * magnitude


# ---------- 链上/基本面 ----------

def _score_trend_factor(ctx: NormalizeContext, factor: str, target_asset: str, up_score=1.0, down_score=-1.0) -> float | None:
    if ctx.asset != target_asset:
        return None
    today = ctx.today_value(factor)
    hist = ctx.history_before_today(factor)
    if today is None:
        return None
    return score_by_trend(today, hist, window=7, up_score=up_score, down_score=down_score)


def score_eth_defi_tvl(ctx: NormalizeContext) -> float | None:
    return _score_trend_factor(ctx, "chain_tvl", "ETH")


def score_sol_defi_tvl(ctx: NormalizeContext) -> float | None:
    return _score_trend_factor(ctx, "chain_tvl", "SOL")


def score_uni_dex_volume(ctx: NormalizeContext) -> float | None:
    return _score_trend_factor(ctx, "dex_volume", "UNI")


def score_uni_protocol_fees(ctx: NormalizeContext) -> float | None:
    return _score_trend_factor(ctx, "protocol_fees", "UNI")


# ---------- 行业周期（只用于 regime，不进单币维度） ----------

def score_fear_greed(ctx: NormalizeContext) -> float | None:
    value = ctx.today_value("fear_greed", asset="MARKET")
    if value is None:
        return None
    return score_by_thresholds(value, [(20, 2.0), (40, 1.0), (60, 0.0), (80, -1.0), (None, -2.0)])


def score_stablecoin_supply(ctx: NormalizeContext) -> float | None:
    value = ctx.today_value("stablecoin_mcap", asset="MARKET")
    hist = ctx.history_before_today("stablecoin_mcap", asset="MARKET")
    if value is None:
        return None
    return score_by_trend(value, hist, window=7, up_score=1.5, down_score=-1.5)


def score_btc_loss_supply_ratio(ctx: NormalizeContext) -> float | None:
    profit_pct = ctx.today_value("supply_profit_pct", asset="BTC")
    if profit_pct is None:
        return None
    loss_pct = 100 - profit_pct
    return score_by_thresholds(loss_pct, [(10, -1.0), (30, 0.0), (50, 1.0), (None, 2.0)])


def score_btc_profit_supply_pct(ctx: NormalizeContext) -> float | None:
    value = ctx.today_value("supply_profit_pct", asset="BTC")
    if value is None:
        return None
    return score_by_thresholds(value, [(50, 1.0), (80, 0.0), (95, -1.0), (None, -2.0)])


# ---------- 衍生品情绪 ----------

def score_funding_rate(ctx: NormalizeContext) -> float | None:
    value = ctx.today_value("funding_rate")
    if value is None:
        return None
    pct = value * 100  # 存的是小数(0.0001=0.01%)，规则表阈值按百分比
    # 边界是用户确认的猜测值，已回填进规则表 F37 格保持表码一致：
    # >0.05%→-2；0.01~0.05%→-0.5；-0.01~0.01%→0；-0.05~-0.01%→+1；<-0.05%→+2
    if pct > 0.05:
        return -2.0
    if pct > 0.01:
        return -0.5
    if pct > -0.01:
        return 0.0
    if pct > -0.05:
        return 1.0
    return 2.0


def score_open_interest(ctx: NormalizeContext) -> float | None:
    oi_series = ctx.factor_series("open_interest").sort_index()
    price_series = ctx.factor_series("close_price").sort_index()
    if ctx.target_date not in oi_series.index or ctx.target_date not in price_series.index:
        return None

    oi_hist = oi_series[oi_series.index < ctx.target_date]
    if oi_hist.empty:
        return None
    oi_baseline = oi_hist.tail(7).mean()
    if oi_baseline == 0 or pd.isna(oi_baseline):
        return None
    oi_change_pct = (oi_series[ctx.target_date] - oi_baseline) / abs(oi_baseline)

    price_idx = price_series.index.get_loc(ctx.target_date)
    if price_idx == 0:
        return None
    price_change = price_series.iloc[price_idx] - price_series.iloc[price_idx - 1]

    if oi_change_pct > 0.02 and price_change > 0:
        return -0.5
    if oi_change_pct > 0.02 and price_change <= 0:
        return 0.5
    return 0.0


def score_long_short_ratio(ctx: NormalizeContext) -> float | None:
    today = ctx.today_value("long_short_ratio")
    hist = ctx.history_before_today("long_short_ratio")
    if today is None:
        return None
    pct = percentile_rank(today, hist, min_history=30)
    if pct is None:
        return None
    if pct >= 0.9:  # 多头账户占比处于历史高位 = 极度看多 = 反指看空
        return -1.0
    if pct <= 0.1:
        return 1.0
    return 0.0


def score_dvol(ctx: NormalizeContext) -> float | None:
    if ctx.asset not in ("BTC", "ETH"):
        return None
    today = ctx.today_value("dvol")
    hist = ctx.history_before_today("dvol")
    if today is None:
        return None
    pct = percentile_rank(today, hist, min_history=30)
    if pct is None:
        return None
    if pct >= 0.9:
        return 1.0
    if pct <= 0.1:
        return -0.5
    return 0.0


def score_coinbase_premium(ctx: NormalizeContext) -> float | None:
    if ctx.asset != "BTC":
        return None
    value = ctx.today_value("coinbase_premium")
    if value is None:
        return None
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


# ---------- 宏观（只用于 regime，不进单币维度） ----------

def score_fed_funds_rate(ctx: NormalizeContext) -> float | None:
    """降级实现：见模块顶部 DEGRADED_FACTORS 说明。"""
    today = ctx.today_value("fed_funds_rate", asset="MACRO")
    hist = ctx.history_before_today("fed_funds_rate", asset="MACRO")
    if today is None:
        return None
    return score_by_trend(today, hist, window=30, up_score=-1.5, down_score=1.5, flat_band_pct=0.01)


def score_m2_yoy(ctx: NormalizeContext) -> float | None:
    today = ctx.today_value("m2", asset="MACRO")
    hist = ctx.history_before_today("m2", asset="MACRO")
    if today is None:
        return None
    return score_by_trend(today, hist, window=30, up_score=1.5, down_score=-1.5, flat_band_pct=0.05)


def score_treasury_10y(ctx: NormalizeContext) -> float | None:
    today = ctx.today_value("treasury_10y", asset="MACRO")
    hist = ctx.history_before_today("treasury_10y", asset="MACRO")
    if today is None or hist.empty:
        return None
    baseline = hist.tail(7).mean()
    if pd.isna(baseline):
        return None
    change = today - baseline  # 绝对变化（百分点），不是相对百分比
    if change < -0.05:
        return 1.0
    if change > 0.15:
        return -2.0
    return 0.0


NORMALIZERS = {
    "价格 vs MA50": score_price_vs_ma50,
    "价格 vs MA200": score_price_vs_ma200,
    "MA50 vs MA200 排列": score_ma_cross,
    "RSI 日线": score_rsi_daily,
    "MACD 日线柱": score_macd_daily,
    "布林带位置": score_bollinger_position,
    "相对强度 币/BTC": score_relative_strength,
    "交易所净流入流出": score_exchange_netflow,
    "成交量 vs 20日均量": score_volume_vs_avg,
    "ETH DeFi TVL": score_eth_defi_tvl,
    "SOL DeFi TVL": score_sol_defi_tvl,
    "UNI 协议日交易量": score_uni_dex_volume,
    "UNI 费用收入": score_uni_protocol_fees,
    "恐慌贪婪指数": score_fear_greed,
    "稳定币总量": score_stablecoin_supply,
    "BTC 亏损供应比": score_btc_loss_supply_ratio,
    "BTC 利润供应%": score_btc_profit_supply_pct,
    "资金费率": score_funding_rate,
    "未平仓 OI": score_open_interest,
    "大户多空比": score_long_short_ratio,
    "波动率指数 DVOL": score_dvol,
    "Coinbase 溢价": score_coinbase_premium,
    "联邦基金利率/路径": score_fed_funds_rate,
    "M2 同比": score_m2_yoy,
    "美债10Y收益率": score_treasury_10y,
}
