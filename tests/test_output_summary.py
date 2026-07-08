import json

import pandas as pd

from ha_backtest.core.output import summarize_output


def test_summarize_output_returns_full_exposure_range_and_equity_series(tmp_path):
    rows = [
        {"date": date.strftime("%Y-%m-%d"), "symbol": "SH600000", "target_weight": 0.5}
        for date in pd.date_range("2024-07-02", periods=130, freq="D")
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "target_weights.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"date": "2024-07-02"}]).to_csv(
        tmp_path / "ha_premium_history.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(
        [{"a_code": "SH600000", "name": "sample", "premium_rate": 1.23}]
    ).to_csv(tmp_path / "last_premium_snapshot.csv", index=False, encoding="utf-8-sig")

    traces = [
        {
            "name": "equity",
            "x": ["2024-07-02T00:00:00+08:00", "2024-07-03T00:00:00+08:00"],
            "y": [1_000_000.0, 1_010_000.0],
        }
    ]
    report_html = f"Equity & Drawdown Plotly.newPlot('chart', {json.dumps(traces)}, {{}})"
    (tmp_path / "akquant_ha_report.html").write_text(report_html, encoding="utf-8")

    summary = summarize_output(tmp_path, "")

    assert len(summary["exposureSeries"]) == 130
    assert summary["exposureSeries"][0] == {"date": "2024-07-02", "value": 0.5}
    assert summary["equitySeries"] == [
        {"date": "2024-07-02", "value": 1000000.0},
        {"date": "2024-07-03", "value": 1010000.0},
    ]
