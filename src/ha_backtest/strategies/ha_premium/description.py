from __future__ import annotations

from pathlib import Path
from typing import Optional


def write_strategy_description(
    output_dir: Path,
    start_date: str,
    end_date: str,
    pair_count: int,
    cache_dir: Path,
    refresh: bool,
    fx_csv: Optional[Path],
    initial_cash: float,
    min_premium: float,
    gross_exposure: float,
    integer_percent: bool,
    report: bool,
    annual_line_filter: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "strategy_description.md"
    annual_line_formula = "A 股年线 = A 股收盘价的 250 个交易日移动平均\n" if annual_line_filter else ""
    annual_line_parameter = f"- 是否启用 A 股年线交易门槛：`{annual_line_filter}`\n"
    position_rules = """1. 将所有可用 AH 标的按 `H/A 溢价率` 从高到低排序。
2. 取前 30 只计算平均溢价率 `top30_avg`；如果当天不足 30 只，则用当天全部可用标的计算。
3. 取前 10 只作为候选持仓，交易标的是对应 A 股代码（如 `SH600036` / `SZ300750`），不是 H 股代码。
4. 对每只候选标的计算相对前 30 均值的偏移量："""
    annual_line_rule = ""
    sell_rule = "8. 当天不在目标列表里的 A 股旧持仓会被卖出。"
    if annual_line_filter:
        annual_line_rule = "8. 年线过滤版只对候选持仓中 `A 股收盘价 > A 股 250 日均线` 的标的执行目标仓位；低于、等于或缺少年线的候选标的目标仓位归零，不用后续排名标的补位，也不把仓位重新分配给其他股票。"
        sell_rule = "9. 当天不在目标列表里的 A 股旧持仓会被卖出；如果旧持仓跌到 250 日均线以下，也会因为目标权重变为 0 而触发卖出。"

    text = f"""# H/A 溢价 Top30 均值偏移 A 股交易策略

## 运行参数

- 开始日期：`{start_date}`
- 结束日期：`{end_date}`
- AH 标的数量：`{pair_count}`
- 初始资金：`{initial_cash}`
- 最大总仓位：`{gross_exposure:.4f}`
- 是否使用整数百分比仓位：`{integer_percent}`
{annual_line_parameter}- 最低溢价参数：`{min_premium}`（当前 Top30 均值偏移策略不使用该参数）
- 缓存目录：`{cache_dir}`
- 是否强制刷新数据：`{refresh}`
- 本地汇率 CSV：`{fx_csv or "无"}`
- 是否生成 HTML 报告：`{report}`

## 数据构造

```text
H 股人民币收盘价 = H 股港币收盘价 * HKD/CNY
{annual_line_formula}H/A 溢价率 = (H 股人民币收盘价 / A 股收盘价 - 1) * 100
```

## 仓位规则

每个交易日单独计算一次目标仓位：

{position_rules}

```text
offset = premium_rate - top30_avg
```

5. 将偏移量的百分点直接转换为原始仓位：

```text
raw_weight = offset / 100
```

6. 如果原始仓位总和小于等于最大总仓位，则保留原始仓位，剩余资金空仓。
7. 如果原始仓位总和大于最大总仓位，则按比例缩放，使总仓位等于最大总仓位。
{annual_line_rule}
{sell_rule}

## 输出文件

- `akquant_ha_report.html`：本次 AKQuant 回测报告。
- `ha_premium_history.csv`：本次重新计算的每日 H/A 溢价历史。
- `target_weights.csv`：按上述规则生成的每日 A 股目标仓位。
- `last_premium_snapshot.csv`：最后一个可用交易日的溢价快照。
- `strategy_description.md`：本文件，记录本次策略说明和运行参数。
"""
    path.write_text(text, encoding="utf-8")
    return path