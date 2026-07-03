from pathlib import Path

import pandas as pd

from ha_backtest.cli import _make_run_output_dir
from ha_backtest.data import AHPair, AkshareHistoryClient, build_target_weights, load_ah_pairs, normalize_fx
from ha_backtest.runner import write_strategy_description


def test_load_default_pairs_keeps_h_code_padding_and_a_trade_symbol():
    pairs = load_ah_pairs(Path("config/ah_pairs.csv"))

    assert pairs[0].a_code == "SZ300750"
    assert pairs[0].h_code == "03750"
    assert pairs[0].a_trade_symbol == "SZ300750"
    assert pairs[0].trade_symbol == "HK03750"


def test_build_target_weights_uses_a_share_symbols_for_top10_offsets_from_top30_average():
    premium = pd.DataFrame(
        [
            {
                "date": "2026-07-01",
                "a_code": f"SH600{i:03d}",
                "trade_symbol": f"HK{i:05d}",
                "premium_rate": float(31 - i),
            }
            for i in range(1, 31)
        ]
    )

    weights = build_target_weights(premium)

    assert list(weights["symbol"]) == [f"SH600{i:03d}" for i in range(1, 11)]
    assert weights["target_weight"].round(6).tolist() == [
        0.145,
        0.135,
        0.125,
        0.115,
        0.105,
        0.095,
        0.085,
        0.075,
        0.065,
        0.055,
    ]


def test_build_target_weights_scales_offsets_when_total_exceeds_cap():
    rows = [
        {
            "date": "2026-07-01",
            "a_code": f"SZ000{i:03d}",
            "trade_symbol": f"HK{i:05d}",
            "premium_rate": premium,
        }
        for i, premium in enumerate([100.0] * 10 + [0.0] * 20, start=1)
    ]

    weights = build_target_weights(pd.DataFrame(rows))

    assert len(weights) == 10
    assert list(weights["symbol"]) == [f"SZ000{i:03d}" for i in range(1, 11)]
    assert weights["target_weight"].round(6).tolist() == [0.1] * 10
    assert round(float(weights["target_weight"].sum()), 6) == 1.0


def test_normalize_fx_converts_100_hkd_quote_to_single_hkd():
    raw = pd.DataFrame({"date": ["2026-07-01"], "close": [91.25]})

    fx = normalize_fx(raw)

    assert fx["hkd_cny"].iloc[0] == 0.9125


def test_sqlite_cache_fetches_only_missing_prefix(tmp_path):
    client = AkshareHistoryClient(tmp_path)
    client._upsert_ohlcv(
        market="h",
        symbol="03968",
        trade_symbol="HK03968",
        df=pd.DataFrame(
            [
                {"date": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"date": "2026-01-03", "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 200},
            ]
        ),
    )
    calls = []

    def fetch_range(start_date, end_date):
        calls.append((start_date, end_date))
        return pd.DataFrame(
            [
                {"date": "2025-12-31", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 50},
            ]
        )

    result = client._cached_ohlcv(
        market="h",
        symbol="03968",
        trade_symbol="HK03968",
        start_date="20251231",
        end_date="20260103",
        fetch=fetch_range,
        empty_on_failure=True,
    )

    assert calls == [("20251231", "20260101")]
    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-12-31", "2026-01-02", "2026-01-03"]
    assert result["symbol"].tolist() == ["HK03968", "HK03968", "HK03968"]


def test_make_run_output_dir_uses_unique_subdir(tmp_path):
    first = _make_run_output_dir(tmp_path, "20230702", "20260702")
    first.mkdir(parents=True)

    second = _make_run_output_dir(tmp_path, "20230702", "20260702")

    assert first.parent == tmp_path
    assert second.parent == tmp_path
    assert first.name.startswith("run_20230702_20260702_")
    assert second.name.startswith(first.name + "_")
    assert second != first


def test_write_strategy_description_saves_run_notes(tmp_path):
    path = write_strategy_description(
        output_dir=tmp_path,
        start_date="20230702",
        end_date="20260702",
        pair_count=50,
        cache_dir=Path("data/cache"),
        refresh=False,
        fx_csv=None,
        initial_cash=1_000_000,
        min_premium=0.0,
        gross_exposure=1.0,
        integer_percent=False,
        report=True,
    )

    content = path.read_text(encoding="utf-8")

    assert path == tmp_path / "strategy_description.md"
    assert "A 股交易策略" in content
    assert "20230702" in content
    assert "交易标的是对应 A 股代码" in content
    assert "target_weights.csv" in content
