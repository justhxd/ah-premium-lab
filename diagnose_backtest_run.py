from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from ha_backtest.core.context import StrategyRunRequest
from ha_backtest.core.registry import get_strategy
from ha_backtest.data import AkshareHistoryClient, _lookback_start_date, load_ah_pairs


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def install_fetch_trace() -> None:
    original = AkshareHistoryClient._fetch_with_retries

    def traced(self, label, fetch, empty_on_failure):
        started = time.perf_counter()
        log(f"FETCH_BEGIN {label}")
        try:
            frame = original(self, label, fetch, empty_on_failure)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            log(f"FETCH_ERROR {label} elapsed={elapsed:.1f}s error={exc!r}")
            raise
        elapsed = time.perf_counter() - started
        failed = bool(frame.attrs.get("fetch_failed"))
        log(f"FETCH_END {label} rows={len(frame)} failed={failed} elapsed={elapsed:.1f}s")
        return frame

    AkshareHistoryClient._fetch_with_retries = traced


def make_output_dir(base_dir: Path, start: str, end: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base_dir / f"diag_run_{start}_{end}_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a traced H/A backtest for diagnosis.")
    parser.add_argument("--strategy", default="ha-premium-annual-line")
    parser.add_argument("--start", default="20190702")
    parser.add_argument("--end", default="20260702")
    parser.add_argument("--pairs", type=Path, default=Path("config/ah_pairs_full.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--gross-exposure", type=float, default=1.0)
    parser.add_argument("--min-premium", type=float, default=0.0)
    parser.add_argument("--integer-percent", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    install_fetch_trace()
    pairs = load_ah_pairs(args.pairs)
    output_dir = make_output_dir(args.output_dir, args.start, args.end)

    client = AkshareHistoryClient(args.cache_dir, refresh=args.refresh)
    lookback_start = _lookback_start_date(args.start, 250)
    missing_a = [
        (pair.a_code, client._missing_ranges_ohlcv("a", pair.a_symbol, lookback_start, args.end))
        for pair in pairs
    ]
    missing_a = [(code, ranges) for code, ranges in missing_a if ranges]

    log(f"strategy={args.strategy} pairs={len(pairs)} start={args.start} end={args.end}")
    log(f"output_dir={output_dir}")
    log(f"annual_line_lookback_start={lookback_start} missing_a_symbols={len(missing_a)}")
    for code, ranges in missing_a[:20]:
        log(f"MISSING_A {code} ranges={ranges}")
    if len(missing_a) > 20:
        log(f"MISSING_A remaining={len(missing_a) - 20}")

    request = StrategyRunRequest(
        strategy_id=args.strategy,
        pairs=pairs,
        start_date=args.start,
        end_date=args.end,
        cache_dir=args.cache_dir,
        output_dir=output_dir,
        refresh=args.refresh,
        fx_csv=None,
        initial_cash=args.initial_cash,
        min_premium=args.min_premium,
        gross_exposure=args.gross_exposure,
        integer_percent=args.integer_percent,
        report=not args.no_report,
    )
    log("RUN_BEGIN")
    result = get_strategy(args.strategy).run(request)
    log("RUN_END")
    log(str(result.run_summary))
    log(f"output={result.output_dir}")


if __name__ == "__main__":
    main()
