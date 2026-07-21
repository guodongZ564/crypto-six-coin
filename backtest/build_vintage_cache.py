"""一次性构建宏观因子的 point-in-time 缓存：data/alfred_vintage_macro.parquet。

只在需要跑回测/更新回测窗口时手动跑，不是每日流程的一部分——修正历史拉一次
就够，不需要每天重新拉。跟 factor_timeseries.parquet 用同样的长表 schema
(date|asset|factor|value|source)，source 固定标 "alfred_pit" 以跟线上用的
"fred(revised)" 区分开，回测脚本靠这个 source 挑数据。

fed_funds_rate/treasury_10y 实测几乎不被修正(每次新vintage只是新增一天/一月
的数据，不改历史值)，但还是走同一套 point-in-time 流程，不做"这两个不用管"
的特殊判断——统一处理更不容易埋坑，成本也就多几次API调用。
"""

import sys
from datetime import date

import pandas as pd

from backtest import fred_vintage
from core import store

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CACHE_PATH = "data/alfred_vintage_macro.parquet"
SOURCE = "alfred_pit"

# treasury_10y (DGS10) 不在这里：实测过它是日频、逐日追加、从没被修正过
# （5069个"vintage"全部只是"新的一天被加进来"，不是数值订正），而且它的宽
# realtime区间请求会撞 FRED "最多2000个vintage日期"的接口限制，硬修反而
# 麻烦。日频数据本身发布延迟也就1个交易日，对3~20天持仓周期的系统可以忽略，
# 回测直接用 factor_timeseries.parquet 里已经采集好的值，不单独做
# point-in-time 修正——这是记录在案的简化，不是疏漏。
SERIES = {
    "fed_funds_rate": {"id": "FEDFUNDS", "transform": "lin"},  # 没有真实数值修正，但月频数据有~1周发布延迟，需要按发布时间对齐
    "m2": {"id": "M2SL", "transform": "yoy"},  # 有真实数值修正(实测过)，也有发布延迟
}


def build_series(factor: str, series_id: str, transform: str, observation_start: str, observation_end: str) -> pd.DataFrame:
    vintage_df = fred_vintage.fetch_vintage_history(series_id, observation_start, observation_end)
    print(f"[vintage] {factor} ({series_id}): {len(vintage_df)} 条修正记录")

    if transform == "yoy":
        daily = fred_vintage.build_yoy_point_in_time_daily(vintage_df, observation_start, observation_end)
    else:
        daily = fred_vintage.build_point_in_time_daily(vintage_df, observation_start, observation_end)

    if daily.empty:
        return pd.DataFrame(columns=["date", "asset", "factor", "value", "source"])

    return pd.DataFrame({
        "date": daily["date"],
        "asset": "MACRO",
        "factor": factor,
        "value": daily["value"],
        "source": SOURCE,
    })


def main():
    # 宏观 vintage 只对我们实际回测会用到的窗口有意义：加密价格数据最早也就
    # 2017年起，往前多留一年当 YoY/趋势基线的缓冲
    observation_start = "2016-01-01"
    observation_end = date.today().isoformat()

    for factor, spec in SERIES.items():
        df = build_series(factor, spec["id"], spec["transform"], observation_start, observation_end)
        store.upsert(CACHE_PATH, df)
        print(f"[vintage] {factor}: 写入 {len(df)} 行")


if __name__ == "__main__":
    main()
