from __future__ import annotations

from typing import Protocol

from .context import StrategyMetadata, StrategyRunRequest, StrategyRunResult
from ..strategies.ha_premium import HAPremiumAnnualLineStrategySpec, HAPremiumStrategySpec
from ..strategies.sector_flow import SectorFlowRelativeStrengthStrategySpec


class StrategySpec(Protocol):
    metadata: StrategyMetadata

    def run(self, request: StrategyRunRequest) -> StrategyRunResult:
        ...

def run_strategy_preflight(strategy: StrategySpec, request: StrategyRunRequest) -> None:
    preflight = getattr(strategy, "preflight", None)
    if callable(preflight):
        preflight(request)


_STRATEGIES: dict[str, StrategySpec] = {
    HAPremiumStrategySpec.metadata.id: HAPremiumStrategySpec(),
    HAPremiumAnnualLineStrategySpec.metadata.id: HAPremiumAnnualLineStrategySpec(),
    SectorFlowRelativeStrengthStrategySpec.metadata.id: SectorFlowRelativeStrengthStrategySpec(),
}


def get_strategy(strategy_id: str) -> StrategySpec:
    try:
        return _STRATEGIES[strategy_id]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {strategy_id}") from exc


def list_strategy_metadata() -> list[StrategyMetadata]:
    return [strategy.metadata for strategy in _STRATEGIES.values()]
