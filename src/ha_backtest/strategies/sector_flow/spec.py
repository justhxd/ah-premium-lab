from __future__ import annotations

from ...core.backtest import run_target_weight_backtest
from ...core.context import StrategyMetadata, StrategyRunRequest, StrategyRunResult
from .description import write_strategy_description
from .features import (
    LOOKBACK_DAYS,
    SECTOR_POOL_SIZE,
    TOP_SECTORS,
    TOP_STOCKS_PER_SECTOR,
    build_sector_flow_and_weights,
)


class SectorFlowRelativeStrengthStrategySpec:
    metadata = StrategyMetadata(
        id="sector-flow-relative-strength",
        name="行业资金流比价龙头 MVP",
        description="先按行业资金流改善和行业指数相对强弱选强板块，再买入板块内跑赢行业且量能放大的龙头股。",
        command="run",
    )

    def run(self, request: StrategyRunRequest) -> StrategyRunResult:
        built = build_sector_flow_and_weights(
            start_date=request.start_date,
            end_date=request.end_date,
            cache_dir=request.cache_dir,
            output_dir=request.output_dir,
            refresh=request.refresh,
            gross_exposure=request.gross_exposure,
            integer_percent=request.integer_percent,
            sector_pool_size=SECTOR_POOL_SIZE,
            top_sectors=TOP_SECTORS,
            top_stocks_per_sector=TOP_STOCKS_PER_SECTOR,
            lookback_days=LOOKBACK_DAYS,
        )
        result = run_target_weight_backtest(
            market_data=built.market_data,
            weights=built.weights,
            initial_cash=request.initial_cash,
        )

        write_strategy_description(
            output_dir=request.output_dir,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
            gross_exposure=request.gross_exposure,
            integer_percent=request.integer_percent,
            sector_pool_size=SECTOR_POOL_SIZE,
            top_sectors=TOP_SECTORS,
            top_stocks_per_sector=TOP_STOCKS_PER_SECTOR,
            lookback_days=LOOKBACK_DAYS,
            refresh=request.refresh,
            report=request.report,
        )

        if request.report:
            report_path = request.output_dir / "akquant_ha_report.html"
            result.report(filename=str(report_path), show=False)
            _retitle_akquant_report(report_path, f"{self.metadata.name}回测报告")

        return StrategyRunResult(
            output_dir=request.output_dir,
            engine_result=result,
            run_summary=str(result),
        )


def _retitle_akquant_report(report_path, title: str) -> None:
    if not report_path.exists():
        return
    html = report_path.read_text(encoding="utf-8", errors="ignore")
    html = html.replace("AKQuant 策略回测报告", title)
    report_path.write_text(html, encoding="utf-8")
