"""评分有效性指标（IC/胜率/t值/分档单调性）+ 策略绩效指标（年化/回撤/夏普/
胜率/持有天数/交易次数）。都是纯统计计算，不碰任何未来数据——调用方负责
保证传进来的 forward_return 已经是"当天分数 vs 之后N天收益"这种正确配对，
这个模块本身不做任何 point-in-time 相关的事。
"""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 365  # 加密24/7交易，不用股票的252


def forward_return(close_series: pd.Series, horizon_days: int) -> pd.Series:
    """close_series: index=date字符串(升序)。返回同索引的"未来horizon_days天收益率"，
    最后 horizon_days 天没有未来数据，是 NaN。"""
    shifted = close_series.shift(-horizon_days)
    return shifted / close_series - 1


def rank_ic(scores: pd.Series, returns: pd.Series) -> dict:
    """scores/returns 用同一个 index 对齐；NaN 自动跳过。返回 ic/t值/胜率/样本数。"""
    paired = pd.DataFrame({"score": scores, "return": returns}).dropna()
    n = len(paired)
    if n < 10:
        return {"ic": None, "t_stat": None, "win_rate": None, "n": n}

    ic = paired["score"].corr(paired["return"], method="spearman")
    if ic is None or np.isnan(ic):
        return {"ic": None, "t_stat": None, "win_rate": None, "n": n}

    if abs(ic) >= 1:
        t_stat = float("inf") if ic > 0 else float("-inf")
    else:
        t_stat = ic * np.sqrt((n - 2) / (1 - ic ** 2))

    directional = paired[paired["score"] != 0]
    if directional.empty:
        win_rate = None
    else:
        hits = np.sign(directional["score"]) == np.sign(directional["return"])
        win_rate = float(hits.mean())

    return {"ic": float(ic), "t_stat": float(t_stat), "win_rate": win_rate, "n": n}


def monotonicity_table(actions: pd.Series, returns: pd.Series, action_order: list) -> pd.DataFrame:
    """按动作档分组算未来收益均值，action_order 是从最看多到最看空的档位顺序，
    用来检查"强烈看多>看多>中性>看空>强烈看空"是否成立。"""
    paired = pd.DataFrame({"action": actions, "return": returns}).dropna()
    grouped = paired.groupby("action")["return"].agg(["mean", "count"])
    grouped = grouped.reindex(action_order)
    return grouped


def is_monotonic_decreasing(mean_returns: pd.Series) -> bool:
    values = mean_returns.dropna().tolist()
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def strategy_performance(daily_returns: pd.Series, positions: pd.Series) -> dict:
    """daily_returns: 每天扣完摩擦成本后的策略日收益率；positions: 每天的仓位(0~1)。"""
    daily_returns = daily_returns.dropna()
    if daily_returns.empty:
        return {
            "annualized_return": None, "max_drawdown": None, "sharpe": None,
            "win_rate": None, "avg_holding_days": None, "trade_count": None, "n_days": 0,
        }

    equity = (1 + daily_returns).cumprod()
    n_days = len(daily_returns)
    total_return = equity.iloc[-1] - 1
    annualized_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1 if n_days > 0 else None

    std = daily_returns.std()
    sharpe = float(daily_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std and std > 0 else None

    nonzero_days = daily_returns[positions.reindex(daily_returns.index).fillna(0) != 0]
    win_rate = float((nonzero_days > 0).mean()) if not nonzero_days.empty else None

    pos = positions.fillna(0)
    holding_episodes = []
    current_len = 0
    trade_count = 0
    prev_pos = 0.0
    for p in pos:
        if p != prev_pos:
            trade_count += 1
        if p != 0:
            current_len += 1
        elif current_len > 0:
            holding_episodes.append(current_len)
            current_len = 0
        prev_pos = p
    if current_len > 0:
        holding_episodes.append(current_len)

    avg_holding_days = float(np.mean(holding_episodes)) if holding_episodes else None

    return {
        "annualized_return": float(annualized_return) if annualized_return is not None else None,
        "max_drawdown": _max_drawdown(equity),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "avg_holding_days": avg_holding_days,
        "trade_count": trade_count,
        "n_days": n_days,
        "equity_curve": equity,
    }
