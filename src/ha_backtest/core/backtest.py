from __future__ import annotations

from typing import Any

import pandas as pd

from .target_weights import make_target_weight_strategy


def run_target_weight_backtest(
    *,
    market_data: dict[str, pd.DataFrame],
    weights: pd.DataFrame,
    initial_cash: float,
) -> Any:
    try:
        import akquant as aq
    except ModuleNotFoundError as exc:
        raise RuntimeError("akquant is not installed. Run: python -m pip install akquant") from exc
    except ImportError as exc:
        raise RuntimeError(f"akquant is installed but could not be imported: {exc}") from exc

    symbols = sorted(market_data)
    if not symbols:
        raise RuntimeError("No market data was fetched; cannot run backtest.")

    strategy = make_target_weight_strategy(
        weights,
        symbols=symbols,
        expected_symbols_by_date=available_symbols_by_date(market_data),
    )
    return aq.run_backtest(
        data=market_data,
        strategy=strategy,
        symbols=symbols,
        initial_cash=initial_cash,
        lot_size=1,
        fill_policy={"price_basis": "close", "temporal": "same_cycle"},
        show_progress=False,
    )


def available_symbols_by_date(market_data: dict[str, pd.DataFrame]) -> dict[pd.Timestamp, set[str]]:
    available: dict[pd.Timestamp, set[str]] = {}
    for symbol, frame in market_data.items():
        if frame.empty or "date" not in frame:
            continue
        dates = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize().dropna().unique()
        for date in dates:
            available.setdefault(pd.Timestamp(date), set()).add(symbol)
    return available
