from __future__ import annotations

import json
import re
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
        for row in grouped.to_dict(orient="records"):
            exposure_series.append(
                {
                    "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "value": _round_or_none(row["target_weight"], 6),
                }
            )

    latest_exposure = float(latest_weights["target_weight"].sum()) if "target_weight" in latest_weights else 0.0
    report_path = output_dir / "akquant_ha_report.html"
    report_metrics, equity_series = _summarize_akquant_report(report_path)
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
        "reportMetrics": report_metrics,
        "equitySeries": equity_series,
        "weights": weights_rows,
        "exposureSeries": exposure_series,
        "files": files,
    }


def _summarize_akquant_report(report_path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not report_path.exists():
        return {}, []

    text = report_path.read_text(encoding="utf-8", errors="ignore")
    metrics = {
        "totalReturn": _extract_report_metric(text, "Total Return"),
        "annualizedReturn": _extract_report_metric(text, "CAGR"),
        "maxDrawdown": _extract_report_metric(text, "Max DD"),
        "sharpe": _extract_report_metric(text, "Sharpe"),
    }
    metrics = {key: value for key, value in metrics.items() if value}
    return metrics, _extract_equity_series(text)


def summarize_akquant_report(report_path: Path) -> dict[str, str]:
    metrics, _equity_series = _summarize_akquant_report(report_path)
    return metrics


def _extract_report_metric(text: str, label: str) -> Optional[str]:
    pattern = (
        r'<div class="metric-card">\s*'
        r'<div class="metric-value[^"]*">([^<]+)</div>\s*'
        r'<div class="metric-label">[^<]*\(' + re.escape(label) + r'\)</div>'
    )
    match = re.search(pattern, text, re.S)
    return match.group(1).strip() if match else None


def _extract_equity_series(text: str) -> list[dict[str, Any]]:
    section_index = text.find("Equity & Drawdown")
    plot_index = text.find("Plotly.newPlot", max(section_index, 0))
    if plot_index < 0:
        return []

    array_start = text.find("[", plot_index)
    if array_start < 0:
        return []

    raw_data = _read_balanced_json(text, array_start, "[", "]")
    if not raw_data:
        return []

    try:
        traces = json.loads(raw_data)
    except json.JSONDecodeError:
        return []

    equity_trace = next((trace for trace in traces if trace.get("name") == "权益"), traces[0] if traces else {})
    dates = equity_trace.get("x") or []
    values = equity_trace.get("y") or []
    series = []
    for date, value in zip(dates, values):
        if value is None or pd.isna(value):
            continue
        series.append({"date": str(date)[:10], "value": _round_or_none(value, 2)})
    return series


def _read_balanced_json(text: str, start: int, opener: str, closer: str) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _round_or_none(value: Any, digits: int) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)
