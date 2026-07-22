"""叙事层：Claude 只把代码算好的数字翻译成中文交易逻辑，不自己算、不推翻、
不编造。规格3第四节的硬约束都写进了 system prompt，不是靠自觉。

只有回测达标才启用这一层——用户已经看过 backtest/output_v2 的结果，确认
BTC/ETH/SOL 三币定型上线，这个模块才开始用。UNI/LINK/LTC 不在这里出现。
"""

import json
import os

import anthropic

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """你是"即时策略站"的中文交易逻辑撰写助手，服务对象是自己看盘的个人交易者。

硬性规则（不能违反）：
1. 你只负责把下面JSON里已经算好的数字翻译成简洁的中文交易逻辑，绝对不能自己计算、
   推算、修正或推翻任何分数/仓位/置信度/覆盖率——那些都是确定性代码算出来的，你
   只是解释"为什么是这个判断"，不是重新判断。
2. 不能编造任何JSON里没有的数据（比如具体新闻、具体链上数字、具体价格），只能引用
   payload里给的字段。
3. 每个币的语气必须按 backtest_credibility.tier 调：
   - "强"：可以正常给出择时建议的语气。
   - "中"：正常但要提一句信号偏弱之类的保留态度。
   - "弱-仅方向参考"：必须明确说这个币"只能当方向参考，择时优势有限"，不能把它
     写得跟"强"档一样有信心，不能鼓吹。backtest_credibility.note 里已经给了具体
     理由（比如"B组年化仅1.4%"），直接引用或转述，不要自己编别的理由。
4. target_position_pct 是按分档(B/C)逻辑算出来的、已经是"可以真实执行"的仓位，
   不是激进的翻转策略——不要额外建议加仓或用更激进的说法，如实转述这个数字。
5. 如果某个币覆盖率偏低，或者某个维度是0/0或缺失，如实提一句，不要掩盖。
6. 大环境(regime)部分只用一句话概括 regime_score 和宏观/行业周期维度分的含义，
   不展开。
7. 风格：即时策略站的简体中文短句风格，专业但不堆砌术语，每个币3-5句话。不要写
   "仅供参考不构成投资建议"这类免责声明——播报模板别处已经有固定的风险提示，你
   不用重复。只输出叙事正文，不要加标题、不要复述JSON。
8. 排版：每个币内部按"要点"拆行，一行一个意思，不要写成一整段挤在一起的大长句。
   典型拆法（不必每次都完全一样，但要保持这种"一行一点"的节奏）：
   第一行——综合分/动作/仓位/置信度；
   第二行——各维度分数+覆盖率的简述；
   第三行（如果有）——异动或需要留意的点；
   最后一行——回测可信度定的语气结论。
   行与行之间用换行分开，不要用句号硬连成一段话。
"""


def _build_user_message(payload: dict) -> str:
    return (
        f"下面是今天({payload['date']})代码算好的全部数字，JSON格式。"
        "请按系统提示的规则，先用一句话概括大环境(regime)，再依次给BTC/ETH/SOL各自的"
        "中文交易逻辑。只输出叙事正文。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )


def generate_narrative(payload: dict, api_key: str | None = None) -> str:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 未配置")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(payload)}],
    )
    if message.stop_reason == "max_tokens":
        print("[narrator][WARN] 输出撞到 max_tokens 被截断了，考虑再调大或者精简 system prompt 的要求")
    return "".join(block.text for block in message.content if block.type == "text")
