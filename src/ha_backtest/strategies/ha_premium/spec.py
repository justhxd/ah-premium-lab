from __future__ import annotations

from ...core.backtest import run_target_weight_backtest
from ...core.context import StrategyMetadata, StrategyRunRequest, StrategyRunResult
from ...data import build_a_share_market_data
from .description import write_strategy_description
from .features import build_premium_and_weights


class HAPremiumStrategySpec:
    annual_line_filter = False
    metadata = StrategyMetadata(
        id="ha-premium",
        name="H/A 溢价目标权重回测",
        description="每个交易日按 H/A 溢价排序，取前 10 只并根据 Top30 均值偏移分配仓位。",
        command="run",
    )

    def build_premium_and_weights(self, request: StrategyRunRequest):
        return build_premium_and_weights(
            pairs=request.pairs,
            start_date=request.start_date,
            end_date=request.end_date,
            cache_dir=request.cache_dir,
            output_dir=request.output_dir,
            refresh=request.refresh,
            fx_csv=request.fx_csv,
            min_premium=request.min_premium,
            gross_exposure=request.gross_exposure,
            integer_percent=request.integer_percent,
            annual_line_filter=self.annual_line_filter,
        )

    def run(self, request: StrategyRunRequest) -> StrategyRunResult:
        premium, weights = self.build_premium_and_weights(request)
        market_data = build_a_share_market_data(
            pairs=request.pairs,
            start_date=request.start_date,
            end_date=request.end_date,
            cache_dir=request.cache_dir,
            refresh=request.refresh,
        )
        result = run_target_weight_backtest(
            market_data=market_data,
            weights=weights,
            initial_cash=request.initial_cash,
        )

        write_strategy_description(
            output_dir=request.output_dir,
            start_date=request.start_date,
            end_date=request.end_date,
            pair_count=len(request.pairs),
            cache_dir=request.cache_dir,
            refresh=request.refresh,
            fx_csv=request.fx_csv,
            initial_cash=request.initial_cash,
            min_premium=request.min_premium,
            gross_exposure=request.gross_exposure,
            integer_percent=request.integer_percent,
            report=request.report,
            annual_line_filter=self.annual_line_filter,
        )

        if request.report:
            report_path = request.output_dir / "akquant_ha_report.html"
            result.report(filename=str(report_path), show=False)

        if not premium.empty:
            last_date = premium["date"].max()
            premium[premium["date"] == last_date].to_csv(
                request.output_dir / "last_premium_snapshot.csv",
                index=False,
                encoding="utf-8-sig",
            )

        return StrategyRunResult(
            output_dir=request.output_dir,
            engine_result=result,
            run_summary=str(result),
        )


class HAPremiumAnnualLineStrategySpec(HAPremiumStrategySpec):
    annual_line_filter = True
    metadata = StrategyMetadata(
        id="ha-premium-annual-line",
        name="H/A 溢价年线过滤回测",
        description="每个交易日先按 H/A 溢价排序取前 10 只并根据 Top30 均值偏移计算仓位，再仅对 A 股收盘价高于 250 日均线的标的执行目标仓位。",
        command="run",
    )