"""三组策略仓位规则的单测，重点测组A的"穿越才切换"状态机行为，和组B/C在
现货版下数学等价这个结构性结论（backtest/report.py 里播报的那条警告就是
靠这个事实支撑的，这里用测试把它钉死，以后如果谁改了 tiered/merged 的实现
导致这个等价关系被打破，测试会炸）。
"""

from backtest import strategy


def test_tiered_target_position_bands():
    assert strategy.tiered_target_position(1.5) == 1.0
    assert strategy.tiered_target_position(1.0) == 1.0
    assert strategy.tiered_target_position(0.7) == 0.5
    assert strategy.tiered_target_position(0.4) == 0.5
    assert strategy.tiered_target_position(0.0) == 0.0
    assert strategy.tiered_target_position(-0.5) == 0.0
    assert strategy.tiered_target_position(-1.5) == 0.0
    assert strategy.tiered_target_position(None) == 0.0


def test_flip_state_holds_between_thresholds():
    state = strategy.FlipState()
    # 还没进场，分数在中间地带不动
    assert strategy.flip_target_position(0.2, state) == 0.0
    # 穿过 entry threshold(0.4) 才进场
    assert strategy.flip_target_position(0.5, state) == 1.0
    # 进场后分数回落，只要没跌破清仓线(默认0)就继续持有——注意 0.1 > 0，还没到清仓线
    assert strategy.flip_target_position(0.1, state) == 1.0
    # 跌破清仓线(0)才清空
    assert strategy.flip_target_position(-0.1, state) == 0.0
    # 清空后即使分数回升到中性区也不会自动进场，要再穿一次0.4
    assert strategy.flip_target_position(0.3, state) == 0.0
    assert strategy.flip_target_position(0.4, state) == 1.0


def test_flip_state_custom_clear_line():
    state = strategy.FlipState(in_position=True)
    assert strategy.flip_target_position(-0.3, state, clear_line=-0.4) == 1.0  # 还没跌破-0.4
    assert strategy.flip_target_position(-0.5, state, clear_line=-0.4) == 0.0


def test_merged_equals_tiered_in_spot_only_mode():
    """结构性结论：现货版下，clear_line 只要不超过0.4，组C(合并)恒等于组B(纯分档)
    ——分档表本身已经把 <0.4 的分数全部映射成0仓位，清仓线的触发范围是它的
    子集，不会产生任何独立于分档之外的动作。"""
    import numpy as np

    for clear_line in [0.0, -0.2, -0.4]:
        for s in np.arange(-2, 2.01, 0.05):
            b = strategy.tiered_target_position(float(s))
            c = strategy.merged_target_position(float(s), clear_line=clear_line)
            assert b == c, f"clear_line={clear_line} score={s}: B={b} C={c}"


def test_apply_friction():
    assert strategy.apply_friction(0.5, 0.0005) == 0.00025
    assert strategy.apply_friction(0.0, 0.0005) == 0.0
    assert strategy.apply_friction(-1.0, 0.0005) == 0.0005  # 用绝对值，不管方向
