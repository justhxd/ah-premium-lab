from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from .core.backtest import available_symbols_by_date
from .core.context import StrategyRunRequest
from .core.registry import get_strategy
from .data import AHPair
from .strategies.ha_premium.description import write_strategy_description
from .strategies.ha_premium.features import build_premium_and_weights


def run_backtest(
    pairs: Sequence[AHPair],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    output_dir: Path,
    refresh: bool = False,
    fx_csv: Optional[Path] = None,
    initial_cash: float = 1_000_000.0,
    min_premium: float = 0.0,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
    report: bool = True,
):
    request = StrategyRunRequest(
        strategy_id="ha-premium",
        pairs=pairs,
        start_date=start_date,
        end_date=end_date,
        cache_dir=cache_dir,
        output_dir=output_dir,
        refresh=refresh,
        fx_csv=fx_csv,
        initial_cash=initial_cash,
        min_premium=min_premium,
        gross_exposure=gross_exposure,
        integer_percent=integer_percent,
        report=report,
    )
    return get_strategy("ha-premium").run(request).engine_result


def _available_symbols_by_date(market_data: dict[str, pd.DataFrame]) -> dict[pd.Timestamp, set[str]]:
    return available_symbols_by_date(market_data)
