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
    text = f"""# Sector Flow Relative Strength MVP

## Strategy Logic

This MVP first scores industry sectors by improving main-fund flow and relative sector strength, then buys the strongest stocks inside the selected sectors. Stock leadership is defined by outperformance versus its sector plus stronger recent volume.

## Run Parameters

- Backtest window: `{start_date}` to `{end_date}`
- Initial cash: `{initial_cash}`
- Gross exposure cap: `{gross_exposure}`
- Integer-percent weights: `{integer_percent}`
- Sector pool size: `{sector_pool_size}`
- Selected sectors per day: `{top_sectors}`
- Leaders per sector: `{top_stocks_per_sector}`
- Relative-strength window: `{lookback_days}` trading days
- Refresh market cache: `{refresh}`
- Generate AKQuant report: `{report}`

## Output Files

- `sector_flow_features.csv`: sector flow, sector relative strength, and sector scores.
- `stock_leader_scores.csv`: stock relative strength, volume ratio, and leadership scores.
- `target_weights.csv`: daily target weights.
- `last_premium_snapshot.csv`: latest sector signal snapshot.
- `akquant_ha_report.html`: AKQuant backtest report.

## MVP Limits

- Sector constituents come from current Eastmoney constituents, so long historical backtests have constituent survivorship bias.
- Long individual-stock fund-flow history is weak; the MVP uses price relative strength and volume as the stock leader proxy.
- To reduce data-source pressure, the strategy first limits the sector pool by average sector score over the requested window.
"""
    path.write_text(text, encoding="utf-8")
    return path
