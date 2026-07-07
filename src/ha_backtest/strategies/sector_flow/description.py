from __future__ import annotations

from pathlib import Path


def write_strategy_description(
    *,
    output_dir: Path,
    start_date: str,
    end_date: str,
    initial_cash: float,
    gross_exposure: float,
    integer_percent: bool,
    sector_pool_size: int,
    top_sectors: int,
    top_stocks_per_sector: int,
    lookback_days: int,
    refresh: bool,
    report: bool,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "strategy_description.md"
    text = f"""# 行业资金流比价龙头策略 MVP

## 策略逻辑

本策略把缠论里“股票处在市场比价关系中，资金流向变化可以构成买卖系统”的思路拆成两层：先按行业板块资金流和相对强弱选板块，再在入选板块中选相对板块更强、量能更活跃的龙头股。

## 运行参数

- 回测区间：`{start_date}` 到 `{end_date}`
- 初始资金：`{initial_cash}`
- 总仓位上限：`{gross_exposure}`
- 整数百分比权重：`{integer_percent}`
- 行业池规模：`{sector_pool_size}`
- 每日入选行业数：`{top_sectors}`
- 每行业龙头数：`{top_stocks_per_sector}`
- 相对强弱窗口：`{lookback_days}` 个交易日
- 强制刷新行情缓存：`{refresh}`
- 生成 AKQuant 报告：`{report}`

## 输出文件

- `sector_flow_features.csv`：行业资金流、行业指数相对强弱和行业评分。
- `stock_leader_scores.csv`：入选行业成分股的相对强弱、量能和龙头评分。
- `target_weights.csv`：每日目标权重。
- `last_premium_snapshot.csv`：最后一个交易日的行业信号快照。
- `akquant_ha_report.html`：AKQuant 回测报告。

## MVP 限制

- 板块成分股使用东方财富当前成分，历史回测会存在成分股幸存者偏差。
- 个股长历史资金流可得性较弱，MVP 用个股相对板块强弱和量能放大定义龙头；个股资金流适合后续做近端增强或从现在开始每日落库。
- 为控制数据源压力，先按全区间平均行业评分限制行业池规模，再做每日选板块。
"""
    path.write_text(text, encoding="utf-8")
    return path
