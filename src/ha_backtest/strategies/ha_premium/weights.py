from __future__ import annotations

from typing import List

import pandas as pd


_WEIGHT_COLUMNS = ["date", "symbol", "target_weight", "premium_rate", "a_close", "a_ma250"]


def build_target_weights(
    premium_df: pd.DataFrame,
    min_premium: float = 0.0,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
) -> pd.DataFrame:
    if premium_df.empty:
        return _empty_weight_frame()

    source = _mark_annual_line_filter(premium_df)
    frames: List[pd.DataFrame] = []
    for date, group in source.groupby("date", sort=True):
        ranked = group.dropna(subset=["premium_rate"])
        ranked = ranked[ranked["_above_annual_line"]].sort_values("premium_rate", ascending=False).copy()
        if ranked.empty:
            continue

        benchmark = ranked.head(30)
        candidates = ranked.head(10).copy()
        if benchmark.empty or candidates.empty:
            continue

        top30_avg = float(benchmark["premium_rate"].mean())
        candidates["offset"] = candidates["premium_rate"] - top30_avg
        candidates = candidates[candidates["offset"] > 0].copy()
        if candidates.empty:
            continue

        raw_total = float(candidates["offset"].sum())
        exposure_cap_pct = gross_exposure * 100.0
        if raw_total <= 0 or exposure_cap_pct <= 0:
            continue

        if "a_code" in candidates:
            candidates["symbol"] = candidates["a_code"].astype(str).str.upper()
        else:
            candidates["symbol"] = candidates["trade_symbol"]
        if raw_total <= exposure_cap_pct:
            candidates["target_weight"] = candidates["offset"] / 100.0
        else:
            candidates["target_weight"] = candidates["offset"] / raw_total * gross_exposure

        if integer_percent:
            current_exposure = float(candidates["target_weight"].sum())
            if current_exposure > 0:
                candidates["target_weight"] = _largest_remainder_weights(
                    candidates["target_weight"].tolist(), gross_exposure=current_exposure
                )

        frames.append(candidates[[column for column in _WEIGHT_COLUMNS if column in candidates]])

    if not frames:
        return _empty_weight_frame()
    return pd.concat(frames, ignore_index=True)


def _mark_annual_line_filter(premium_df: pd.DataFrame) -> pd.DataFrame:
    frame = premium_df.copy()
    if {"a_close", "a_ma250"}.issubset(frame.columns):
        frame["_above_annual_line"] = pd.to_numeric(frame["a_close"], errors="coerce") > pd.to_numeric(
            frame["a_ma250"], errors="coerce"
        )
    else:
        frame["_above_annual_line"] = True
    return frame


def _empty_weight_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_WEIGHT_COLUMNS)


def _largest_remainder_weights(weights: List[float], gross_exposure: float) -> List[float]:
    basis = 100
    raw = [w / gross_exposure * basis for w in weights]
    floors = [int(x) for x in raw]
    remaining = basis - sum(floors)
    fractions = sorted(enumerate(raw), key=lambda item: item[1] - int(item[1]), reverse=True)
    for idx, _ in fractions[:remaining]:
        floors[idx] += 1
    return [value / basis * gross_exposure for value in floors]
