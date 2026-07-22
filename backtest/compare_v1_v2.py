"""对比第一版(固定分档/6币/无BTC200周MA+月线MACD)和第二版(BTC/ETH/SOL/新因子/
动态分档)的 IC + 分档单调性，只是个一次性对比脚本，不是长期维护的模块。
"""

import json

V1_PATH = "backtest/output/summary.json"
V2_PATH = "backtest/output_v2/summary.json"


def main():
    with open(V1_PATH, encoding="utf-8") as f:
        v1 = json.load(f)
    with open(V2_PATH, encoding="utf-8") as f:
        v2 = json.load(f)

    print(f"{'币种':<6}{'周期':<6}{'v1 IC':>10}{'v1 t值':>10}{'v2 IC':>10}{'v2 t值':>10}")
    for asset in ["BTC", "ETH", "SOL"]:
        for h in ["3", "7", "14"]:
            ic1 = v1["assets"][asset]["ic_results"][h]
            ic2 = v2["assets"][asset]["ic_results"][h]
            print(f"{asset:<6}{h+'日':<6}{ic1['ic']:>10.3f}{ic1['t_stat']:>10.2f}{ic2['ic']:>10.3f}{ic2['t_stat']:>10.2f}")
        print()

    print("=== 分档单调性(7日) ===")
    for asset in ["BTC", "ETH", "SOL"]:
        print(f"\n--- {asset} ---")
        print("v1 (固定±0.4/±1.0):")
        for row in v1["assets"][asset]["monotonicity"]["7"]:
            mean = row.get("mean")
            print(f"  {row['action']:<14} mean={mean*100:.2f}% n={row.get('count')}" if mean is not None else f"  {row['action']:<14} N/A")
        print("v2 (动态70/90分位):")
        for row in v2["assets"][asset]["monotonicity"]["7"]:
            mean = row.get("mean")
            print(f"  {row['action']:<14} mean={mean*100:.2f}% n={row.get('count')}" if mean is not None else f"  {row['action']:<14} N/A")

    print("\n=== 覆盖率 ===")
    for asset in ["BTC", "ETH", "SOL"]:
        print(f"{asset}: v1={v1['assets'][asset]['avg_coverage']*100:.1f}%  v2={v2['assets'][asset]['avg_coverage']*100:.1f}%")


if __name__ == "__main__":
    main()
