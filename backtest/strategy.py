"""三组对照策略的仓位规则。现货为主（没有做空标的），所以规则表里"可做空"
的那半句在这版先不接，看空/强烈看空两档都映射成空仓——如果以后要接合约/
可做空版本，在这里加 allow_short 分支，不动 run_backtest.py 的调用方式。

三组:
- A 纯信号翻转：只有 0%/100% 两档，靠"穿越"驱动状态切换——分数从下方穿过
  ENTRY_THRESHOLD(+0.4) 才进满仓，从上方穿过 clear_line 才清空，中间地带
  不管分数怎么摆都不动，是个双稳态开关，不是每天跟着分数调。
- B 纯分档：每天都按当日合成分重新算目标仓位，没有额外的清仓线兜底——现货
  版下，中性/看空/强烈看空三档目标仓位本来就都是0%，所以B天然就有"分数转差
  就减仓到0"的效果，只是靠-0.4这个分档边界，不是靠可单独调的clear_line。
- C 合并（分档+翻转清仓）：跟B一样每天按分档定目标仓位，但如果分数跌破
  clear_line，不管分档说什么，强制目标仓位=0——clear_line 默认给0，比分档
  自带的-0.4边界更早触发，这才是"急刹车"要体现的效果（默认设成一样就跟B没
  区别了）。
"""

from dataclasses import dataclass

ENTRY_THRESHOLD = 0.4  # 分档表 看多/建仓 的下边界，也是组A"进场"的穿越点
DEFAULT_CLEAR_LINE = 0.0


def tiered_target_position(composite_score: float | None) -> float:
    """现货版分档：≥1.0→100%，0.4~1.0→50%，其余(含None)→0%。"""
    if composite_score is None:
        return 0.0
    if composite_score >= 1.0:
        return 1.0
    if composite_score >= ENTRY_THRESHOLD:
        return 0.5
    return 0.0


@dataclass
class FlipState:
    in_position: bool = False


def flip_target_position(composite_score: float | None, state: FlipState, clear_line: float = DEFAULT_CLEAR_LINE) -> float:
    """组A：双稳态开关，state 由调用方在多天之间持有、传入传出。"""
    if composite_score is None:
        return 1.0 if state.in_position else 0.0

    if not state.in_position and composite_score >= ENTRY_THRESHOLD:
        state.in_position = True
    elif state.in_position and composite_score < clear_line:
        state.in_position = False

    return 1.0 if state.in_position else 0.0


def merged_target_position(composite_score: float | None, clear_line: float = DEFAULT_CLEAR_LINE) -> float:
    """组C：分档目标仓位，但分数跌破清仓线时强制清零，优先级高于分档。"""
    target = tiered_target_position(composite_score)
    if composite_score is not None and composite_score < clear_line:
        return 0.0
    return target


def apply_friction(position_change: float, fee_rate: float) -> float:
    """调仓摩擦成本（手续费+滑点），按仓位变化的绝对值算，单边费率。"""
    return abs(position_change) * fee_rate
