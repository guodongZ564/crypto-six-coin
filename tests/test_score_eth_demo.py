"""用《加密因子打分规则表.xlsx》「3-ETH示例计算」sheet 的输入和结果做基准测试。

这个 sheet 手填了一组因子分（已经是归一化之后的 -2~2 值）和对应维度权重，
公式算出维度分/原始分/regime/合成分/动作，全部逐项手算验证过。这里不走
normalize.py（那些是真实数据的归一化逻辑，跟这个演示用的占位分值无关），
只测 score.py 的聚合数学（加权平均 → regime → 动作分档）是否跟 sheet 一致。
"""

import pytest

from core import rules, score

TOLERANCE = 0.01


@pytest.fixture(scope="module")
def system_config():
    system_config, _factor_rules = rules.load_rule_table()
    return system_config


def test_technical_dimension(system_config):
    pairs = [(1.5, 3), (1, 2), (-0.5, 2), (1, 2), (1, 2)]  # 价格vsMA200, MA50vsMA200, RSI日线, MACD柱, 相对强度
    assert score.weighted_average(pairs) == pytest.approx(0.863636363636364, abs=TOLERANCE)


def test_funding_dimension(system_config):
    pairs = [(2, 3), (0.5, 2), (1, 2)]  # ETF净流入, 交易所净流入流出, 成交量vs均量
    assert score.weighted_average(pairs) == pytest.approx(1.28571428571429, abs=TOLERANCE)


def test_onchain_dimension(system_config):
    pairs = [(1, 2), (1, 2), (-1, 2)]  # ETH质押率, EIP-1559销毁, ETH DeFi TVL
    assert score.weighted_average(pairs) == pytest.approx(0.333333333333333, abs=TOLERANCE)


def test_derivatives_dimension(system_config):
    pairs = [(-0.5, 2), (0, 1), (-0.5, 1)]  # 资金费率, 大户多空比, DVOL
    assert score.weighted_average(pairs) == pytest.approx(-0.375, abs=TOLERANCE)


def test_raw_score(system_config):
    dim_scores = {
        "技术面": 0.863636363636364,
        "资金面": 1.28571428571429,
        "链上/基本面": 0.333333333333333,
        "衍生品情绪": -0.375,
    }
    weights = system_config.coin_dimension_weights
    pairs = [(dim_scores[d], weights[d]) for d in dim_scores]
    raw_score = score.weighted_average(pairs)
    assert raw_score == pytest.approx(0.615367965367965, abs=TOLERANCE)


def test_regime_score_and_multiplier(system_config):
    regime_score = score.regime_score_from_dimensions(0.6, 0.8, system_config.regime_dimension_weights)
    assert regime_score == pytest.approx(0.35, abs=TOLERANCE)

    long_mult, short_mult, label = score._regime_multiplier(regime_score, system_config.regime_bands)
    assert long_mult == pytest.approx(1.1, abs=TOLERANCE)


def test_composite_score_and_action(system_config):
    raw_score = 0.615367965367965
    regime_score = score.regime_score_from_dimensions(0.6, 0.8, system_config.regime_dimension_weights)
    long_mult, _short_mult, _label = score._regime_multiplier(regime_score, system_config.regime_bands)

    composite = raw_score * long_mult
    assert composite == pytest.approx(0.676904761904762, abs=TOLERANCE)

    action, _meaning = score._action_band(composite, system_config.action_bands)
    assert action == "看多 / 建仓"
