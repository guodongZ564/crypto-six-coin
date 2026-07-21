"""维度合成 → regime 叠加 → 单币合成分 → 动作档 → 置信度/覆盖率。

关键设计（跟用户确认过）：
- 单币只用4个维度（技术/资金/链上/衍生品），宏观+行业周期只喂 regime，不进
  单币加权。
- 某维度完全没有效因子时（比如 LINK/LTC 的链上/基本面），该维度直接不计分，
  权重不重分配给其他维度——原始分 = Σ(维度分×维度权重) / Σ(实际有效维度权重)，
  分母只累加"这天真有数据"的维度权重，不是恒定的1.0。effective_dimension_weight
  就是这个分母，播报要显式带出来。
- regime 的"行业周期"侧只用「适用=全市场」（含BTC）的因子，"山寨(非BTC)"专属
  的2个因子（山寨季指数/BTC dominance）不计入 regime——按设计它们未来是山寨币
  专属调节项，暂不实现也不接入这里。
"""

from dataclasses import dataclass, field

import pandas as pd

from core import normalize, rules


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


@dataclass
class DimensionResult:
    dimension: str
    score: float | None  # None = 该维度完全没有效因子
    valid_factor_count: int
    total_factor_count: int  # 规则表里这个维度对该资产"应有"的因子数
    factor_details: list = field(default_factory=list)  # [(factor_name, score, weight, is_degraded), ...]


@dataclass
class RegimeResult:
    date: str
    macro_dimension: DimensionResult
    cycle_dimension: DimensionResult
    regime_score: float
    band_label: str
    long_mult: float
    short_mult: float


@dataclass
class CoinScoreResult:
    date: str
    asset: str
    dimensions: dict
    raw_score: float | None
    effective_dimension_weight: float  # 实际参与计算的维度权重之和 [0,1]
    regime_score: float
    regime_multiplier: float
    composite_score: float | None
    action: str
    action_meaning: str
    confidence: float | None
    valid_factor_count: int
    total_factor_count: int
    degraded_factors: list
    empty_dimensions: list  # 完全 0/N 的维度名


def weighted_average(score_weight_pairs: list) -> float | None:
    """Σ(score×weight)/Σweight，pairs 为空或权重和为0时返回 None。"""
    weight_sum = sum(w for _, w in score_weight_pairs)
    if weight_sum == 0:
        return None
    return sum(s * w for s, w in score_weight_pairs) / weight_sum


def regime_score_from_dimensions(macro_score: float | None, cycle_score: float | None, regime_dimension_weights: dict) -> float:
    weights = regime_dimension_weights
    eff_weight = (weights["宏观"] if macro_score is not None else 0.0) + \
                 (weights["行业周期"] if cycle_score is not None else 0.0)
    if eff_weight == 0:
        return 0.0
    raw = (macro_score or 0.0) * weights["宏观"] + (cycle_score or 0.0) * weights["行业周期"]
    # 维度分落在 [-2,2]；(raw/eff_weight) 是加权平均后的维度分，再 /2 归一到 [-1,1]
    return (raw / eff_weight) / 2


def _compute_dimension(ctx: normalize.NormalizeContext, applicable_rules: list, dimension: str) -> DimensionResult:
    total = len(applicable_rules)
    details = []

    for rule in applicable_rules:
        normalizer = normalize.NORMALIZERS.get(rule.name)
        if normalizer is None:
            continue
        score = normalizer(ctx)
        if score is None:
            continue
        details.append((rule.name, score, rule.weight, rule.name in normalize.DEGRADED_FACTORS))

    dim_score = weighted_average([(s, w) for _, s, w, _ in details])

    return DimensionResult(
        dimension=dimension,
        score=dim_score,
        valid_factor_count=len(details),
        total_factor_count=total,
        factor_details=details,
    )


def _regime_multiplier(regime_score: float, regime_bands: list) -> tuple:
    for band in regime_bands:
        low_ok = band.low is None or regime_score > band.low
        high_ok = band.high is None or regime_score <= band.high
        if low_ok and high_ok:
            return band.long_mult, band.short_mult, band.label
    mid = regime_bands[len(regime_bands) // 2]
    return mid.long_mult, mid.short_mult, mid.label


def _action_band(score: float, action_bands: list) -> tuple:
    for band in action_bands:
        low_ok = band.low is None or score >= band.low
        high_ok = band.high is None or score < band.high
        if low_ok and high_ok:
            return band.action, band.meaning
    last = action_bands[-1]
    return last.action, last.meaning


def compute_regime(history: pd.DataFrame, target_date: str, system_config, factor_rules: list, index: dict | None = None) -> RegimeResult:
    ctx = normalize.NormalizeContext(history=history, index=index, asset="MACRO", target_date=target_date)

    macro_rules = [r for r in factor_rules if r.dimension == "宏观"]
    cycle_rules = [r for r in factor_rules if r.dimension == "行业周期" and "BTC" in r.applicable_assets]

    macro_dim = _compute_dimension(ctx, macro_rules, "宏观")
    cycle_dim = _compute_dimension(ctx, cycle_rules, "行业周期")

    regime_score = regime_score_from_dimensions(macro_dim.score, cycle_dim.score, system_config.regime_dimension_weights)
    long_mult, short_mult, label = _regime_multiplier(regime_score, system_config.regime_bands)
    return RegimeResult(
        date=target_date,
        macro_dimension=macro_dim,
        cycle_dimension=cycle_dim,
        regime_score=regime_score,
        band_label=label,
        long_mult=long_mult,
        short_mult=short_mult,
    )


def compute_coin_score(
    history: pd.DataFrame,
    target_date: str,
    asset: str,
    system_config,
    factor_rules: list,
    regime: RegimeResult,
    index: dict | None = None,
) -> CoinScoreResult:
    ctx = normalize.NormalizeContext(history=history, index=index, asset=asset, target_date=target_date)

    dim_weights = system_config.coin_dimension_weights
    dimensions = {}
    for dim_name in rules.COIN_DIMENSIONS:
        applicable = [r for r in factor_rules if r.dimension == dim_name and asset in r.applicable_assets]
        dimensions[dim_name] = _compute_dimension(ctx, applicable, dim_name)

    weighted_sum = 0.0
    eff_weight = 0.0
    valid_factors = 0
    total_factors = 0
    degraded = []
    all_scores = []
    empty_dimensions = []

    for dim_name, dim in dimensions.items():
        total_factors += dim.total_factor_count
        valid_factors += dim.valid_factor_count
        for name, score, _weight, is_degraded in dim.factor_details:
            all_scores.append(score)
            if is_degraded:
                degraded.append(name)
        if dim.score is not None:
            weighted_sum += dim.score * dim_weights[dim_name]
            eff_weight += dim_weights[dim_name]
        elif dim.total_factor_count > 0:
            empty_dimensions.append(dim_name)

    raw_score = (weighted_sum / eff_weight) if eff_weight > 0 else None

    if raw_score is None:
        composite_score = None
        action, action_meaning = "无法评分", "四个维度全无有效因子"
        confidence = None
        multiplier = 1.0
    else:
        multiplier = regime.long_mult if raw_score >= 0 else regime.short_mult
        composite_score = raw_score * multiplier
        action, action_meaning = _action_band(composite_score, system_config.action_bands)
        if all_scores:
            direction = _sign(composite_score)
            same_direction = sum(1 for s in all_scores if _sign(s) == direction and direction != 0)
            confidence = same_direction / len(all_scores)
        else:
            confidence = None

    return CoinScoreResult(
        date=target_date,
        asset=asset,
        dimensions=dimensions,
        raw_score=raw_score,
        effective_dimension_weight=eff_weight,
        regime_score=regime.regime_score,
        regime_multiplier=multiplier,
        composite_score=composite_score,
        action=action,
        action_meaning=action_meaning,
        confidence=confidence,
        valid_factor_count=valid_factors,
        total_factor_count=total_factors,
        degraded_factors=sorted(set(degraded)),
        empty_dimensions=empty_dimensions,
    )


def compute_all_scores(history: pd.DataFrame, target_date: str, system_config, factor_rules: list) -> tuple:
    """返回 (RegimeResult, {asset: CoinScoreResult})。

    一天的评分要建 7 个 NormalizeContext（regime 1个 + 6币各1个），这里统一
    建一次 index 给全部 7 个共享，避免同一个 (asset,factor) 被重复筛选 7 遍
    ——回测要逐日重算全部历史，这个共享不是可选优化。
    """
    hist_to_date = history[history["date"] <= target_date]
    index = normalize.build_factor_index(hist_to_date)

    regime = compute_regime(hist_to_date, target_date, system_config, factor_rules, index=index)
    coin_results = {
        asset: compute_coin_score(hist_to_date, target_date, asset, system_config, factor_rules, regime, index=index)
        for asset in rules.ALL_ASSETS
    }
    return regime, coin_results
