from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from ...data import AHPair, build_ha_premium_history
from .weights import build_target_weights


def build_premium_and_weights(
    pairs: Sequence[AHPair],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    output_dir: Path,
    refresh: bool = False,
    fx_csv: Optional[Path] = None,
    min_premium: float = 0.0,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    premium = build_ha_premium_history(
        pairs=pairs,
        start_date=start_date,
        end_date=end_date,
        cache_dir=cache_dir,
        refresh=refresh,
        fx_csv=fx_csv,
    )
    weights = build_target_weights(
        premium,
        min_premium=min_premium,
        gross_exposure=gross_exposure,
        integer_percent=integer_percent,
    )
    premium.to_csv(output_dir / "ha_premium_history.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(output_dir / "target_weights.csv", index=False, encoding="utf-8-sig")
    return premium, weights
