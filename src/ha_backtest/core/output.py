from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd


ALLOWED_RESULT_FILES = {
    "akquant_ha_report.html",
    "strategy_description.md",
    "ha_premium_history.csv",
    "target_weights.csv",
    "last_premium_snapshot.csv",
}


def summarize_output(output_dir: Path, run_repr: str) -> dict[str, Any]:
    weights = _read_csv(output_dir / "target_weights.csv")
    premium = _read_csv(output_dir / "ha_premium_history.csv")
    snapshot = _read_csv(output_dir / "last_premium_snapshot.csv")

    latest_weights = pd.DataFrame()
    latest_date = None
    if not weights.empty and "date" in weights:
        weights["date"] = pd.to_datetime(weights["date"], errors="coerce")
        latest_date = weights["date"].max()
        latest_weights = weights[weights["date"] == latest_date].copy()
        latest_weights = latest_weights.sort_values("target_weight", ascending=False).head(20)

    if not snapshot.empty:
        snapshot = snapshot.copy()
        if "a_code" in snapshot:
            snapshot["symbol"] = snapshot["a_code"].astype(str).str.upper()
        elif "trade_symbol" in snapshot:
            snapshot = snapshot.rename(columns={"trade_symbol": "symbol"})
        if "symbol" in snapshot and not latest_weights.empty:
            latest_weights = latest_weights.merge(
                snapshot[["symbol", "name", "premium_rate"]],
                on="symbol",
                how="left",
                suffixes=("", "_snapshot"),
            )
            if "premium_rate_snapshot" in latest_weights:
                latest_weights["premium_rate"] = latest_weights["premium_rate_snapshot"].combine_first(
                    latest_weights.get("premium_rate")
                )

    weights_rows = []
    for row in latest_weights.to_dict(orient="records"):
        weights_rows.append(
            {
                "symbol": row.get("symbol", ""),
                "name": row.get("name") or row.get("symbol", ""),
                "premiumRate": _round_or_none(row.get("premium_rate"), 4),
                "targetWeight": _round_or_none(row.get("target_weight"), 6),
            }
        )

    exposure_series = []
    if not weights.empty and {"date", "target_weight"}.issubset(weights.columns):
        grouped = weights.groupby("date", dropna=True)["target_weight"].sum().reset_index()
        for row in grouped.tail(120).to_dict(orient="records"):
            exposure_series.append(
                {
                    "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "value": _round_or_none(row["target_weight"], 6),
                }
            )

    latest_exposure = float(latest_weights["target_weight"].sum()) if "target_weight" in latest_weights else 0.0
    files = [{"name": filename, "exists": (output_dir / filename).exists()} for filename in sorted(ALLOWED_RESULT_FILES)]
    return {
        "outputDir": str(output_dir),
        "latestDate": pd.Timestamp(latest_date).strftime("%Y-%m-%d") if pd.notna(latest_date) else None,
        "metrics": {
            "premiumRows": int(len(premium)),
            "targetWeightRows": int(len(weights)),
            "latestExposure": _round_or_none(latest_exposure, 6),
            "positionCount": len(weights_rows),
            "runSummary": run_repr,
        },
        "weights": weights_rows,
        "exposureSeries": exposure_series,
        "files": files,
    }


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _round_or_none(value: Any, digits: int) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)
