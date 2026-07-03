from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from ..data import AHPair


@dataclass(frozen=True)
class StrategyMetadata:
    id: str
    name: str
    description: str
    command: str = "run"


@dataclass(frozen=True)
class StrategyRunRequest:
    strategy_id: str
    pairs: Sequence[AHPair]
    start_date: str
    end_date: str
    cache_dir: Path
    output_dir: Path
    refresh: bool = False
    fx_csv: Optional[Path] = None
    initial_cash: float = 1_000_000.0
    min_premium: float = 0.0
    gross_exposure: float = 1.0
    integer_percent: bool = False
    report: bool = True


@dataclass(frozen=True)
class StrategyRunResult:
    output_dir: Path
    engine_result: Any
    run_summary: str
