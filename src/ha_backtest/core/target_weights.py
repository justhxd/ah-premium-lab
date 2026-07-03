from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Set

import pandas as pd


def make_target_weight_strategy(
    weights_df: pd.DataFrame,
    symbols: List[str],
    rebalance_tolerance: float = 0.005,
    expected_symbols_by_date: Optional[Mapping[pd.Timestamp, Set[str]]] = None,
):
    from akquant import Bar, Strategy

    weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    if not weights_df.empty:
        source = weights_df.copy()
        source["date"] = pd.to_datetime(source["date"]).dt.tz_localize(None).dt.normalize()
        for date, group in source.groupby("date"):
            weights_by_date[pd.Timestamp(date)] = dict(zip(group["symbol"], group["target_weight"]))

    expected_by_date: Dict[pd.Timestamp, Set[str]] = {}
    if expected_symbols_by_date:
        for date, day_symbols in expected_symbols_by_date.items():
            expected_by_date[pd.Timestamp(date).tz_localize(None).normalize()] = set(day_symbols)

    class TargetWeightStrategy(Strategy):
        def __init__(self, symbols: List[str]) -> None:
            super().__init__()
            self.symbols = symbols
            self.pending: Dict[int, Set[str]] = defaultdict(set)
            self.rebalance_log: List[tuple[Any, Dict[str, float]]] = []

        def on_bar(self, bar: Bar) -> None:
            date = pd.Timestamp(bar.timestamp, tz="UTC").tz_convert("Asia/Shanghai").normalize().tz_localize(None)
            expected_symbols = expected_by_date.get(date, set(self.symbols))
            if not expected_symbols:
                return

            bucket = self.pending[bar.timestamp]
            bucket.add(bar.symbol)
            if not bucket.issuperset(expected_symbols):
                return

            self.pending.pop(bar.timestamp, None)
            target_weights = weights_by_date.get(date, {})
            self.order_target_weights(
                target_weights=target_weights,
                liquidate_unmentioned=True,
                rebalance_tolerance=rebalance_tolerance,
            )
            self.rebalance_log.append((date, target_weights))

    TargetWeightStrategy.__name__ = "TargetWeightStrategy"
    return TargetWeightStrategy
