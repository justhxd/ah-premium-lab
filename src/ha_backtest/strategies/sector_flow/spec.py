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
    preflight_sector_flow_data_sources,
)


class SectorFlowRelativeStrengthStrategySpec:
    metadata = StrategyMetadata(
        id="sector-flow-relative-strength",
        name="\u884c\u4e1a\u8d44\u91d1\u6d41\u6bd4\u4ef7\u9f99\u5934 MVP",
        description="\u6309\u884c\u4e1a\u8d44\u91d1\u6d41\u6539\u5584\u548c\u884c\u4e1a\u76f8\u5bf9\u5f3a\u5f31\u9009\u677f\u5757\uff0c\u518d\u4e70\u5165\u677f\u5757\u5185\u8dd1\u8d62\u884c\u4e1a\u4e14\u91cf\u80fd\u653e\u5927\u7684\u9f99\u5934\u80a1\u3002",
        command="run",
    )

    def preflight(self, request: StrategyRunRequest) -> None:
        preflight_sector_flow_data_sources(start_date=request.start_date, end_date=request.end_date)

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
            _retitle_akquant_report(report_path, f"{self.metadata.name}\u56de\u6d4b\u62a5\u544a")

        return StrategyRunResult(
            output_dir=request.output_dir,
            engine_result=result,
            run_summary=str(result),
        )


def _retitle_akquant_report(report_path, title: str) -> None:
    if not report_path.exists():
        return
    html = report_path.read_text(encoding="utf-8", errors="ignore")
    html = html.replace("AKQuant \u7b56\u7565\u56de\u6d4b\u62a5\u544a", title)
    report_path.write_text(html, encoding="utf-8")
