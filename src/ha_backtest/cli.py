from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .core.context import StrategyRunRequest
from .core.registry import get_strategy, list_strategy_metadata, run_strategy_preflight
from .data import load_ah_pairs
from .runner import build_premium_and_weights


DEFAULT_PAIRS = Path("config/ah_pairs_full.csv")
DEFAULT_CACHE = Path("data/cache")
DEFAULT_OUTPUT = Path("data")


def main() -> None:
    parser = argparse.ArgumentParser(description="H/A premium recomputation and AKQuant backtest.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = _add_common_args(subparsers.add_parser("build-premium"))
    run_parser = _add_common_args(subparsers.add_parser("run"))
    run_parser.add_argument("--strategy", default="ha-premium", choices=[item.id for item in list_strategy_metadata()])
    run_parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    run_parser.add_argument("--no-report", action="store_true")

    args = parser.parse_args()
    pairs = load_ah_pairs(args.pairs)
    if not pairs:
        raise SystemExit(f"No AH pairs loaded from {args.pairs}")

    if args.command == "build-premium":
        premium, weights = build_premium_and_weights(
            pairs=pairs,
            start_date=args.start,
            end_date=args.end,
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            refresh=args.refresh,
            fx_csv=args.fx_csv,
            min_premium=args.min_premium,
            gross_exposure=args.gross_exposure,
            integer_percent=args.integer_percent,
        )
        print(f"premium rows: {len(premium)}")
        print(f"target weight rows: {len(weights)}")
        print(f"output: {args.output_dir}")
        return

    run_output_dir = _make_run_output_dir(args.output_dir, args.start, args.end)
    request = StrategyRunRequest(
        strategy_id=args.strategy,
        pairs=pairs,
        start_date=args.start,
        end_date=args.end,
        cache_dir=args.cache_dir,
        output_dir=run_output_dir,
        refresh=args.refresh,
        fx_csv=args.fx_csv,
        initial_cash=args.initial_cash,
        min_premium=args.min_premium,
        gross_exposure=args.gross_exposure,
        integer_percent=args.integer_percent,
        report=not args.no_report,
    )
    strategy = get_strategy(args.strategy)
    run_strategy_preflight(strategy, request)
    result = strategy.run(request)
    print(result.engine_result)
    print(f"output: {run_output_dir}")



def _make_run_output_dir(base_dir: Path, start_date: str, end_date: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"run_{start_date}_{end_date}_{timestamp}"
    path = Path(base_dir) / stem
    counter = 2
    while path.exists():
        path = Path(base_dir) / f"{stem}_{counter:02d}"
        counter += 1
    return path


def _add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--fx-csv", type=Path, default=None, help="Optional local HKD/CNY history CSV.")
    parser.add_argument("--min-premium", type=float, default=0.0)
    parser.add_argument("--gross-exposure", type=float, default=1.0)
    parser.add_argument("--integer-percent", action="store_true")
    return parser


if __name__ == "__main__":
    main()
