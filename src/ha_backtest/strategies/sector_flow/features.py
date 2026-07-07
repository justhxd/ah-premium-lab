from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from ...data import AShareSymbol, AkshareHistoryClient, normalize_a_share_trade_symbol

LOOKBACK_DAYS = 20
SECTOR_POOL_SIZE = 12
TOP_SECTORS = 3
TOP_STOCKS_PER_SECTOR = 2
MIN_SECTOR_SCORE = 0.0


@dataclass(frozen=True)
class SectorFlowBuildResult:
    sector_features: pd.DataFrame
    stock_scores: pd.DataFrame
    weights: pd.DataFrame
    market_data: dict[str, pd.DataFrame]


def build_sector_flow_and_weights(
    *,
    start_date: str,
    end_date: str,
    cache_dir: Path,
    output_dir: Path,
    refresh: bool = False,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
    sector_pool_size: int = SECTOR_POOL_SIZE,
    top_sectors: int = TOP_SECTORS,
    top_stocks_per_sector: int = TOP_STOCKS_PER_SECTOR,
    lookback_days: int = LOOKBACK_DAYS,
) -> SectorFlowBuildResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    a_start_date = _lookback_start_date(start_date, lookback_days)
    sector_names = _fetch_industry_names()
    sector_features = build_sector_features(
        _fetch_sector_histories(sector_names, a_start_date, end_date),
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
    )
    sector_pool = select_sector_pool(sector_features, sector_pool_size=sector_pool_size)
    sector_features = sector_features[sector_features["sector_name"].isin(sector_pool)].copy()

    constituents = _fetch_sector_constituents(sector_pool)
    stock_histories = _fetch_stock_histories(
        symbols=_symbols_from_constituents(constituents),
        start_date=a_start_date,
        end_date=end_date,
        cache_dir=cache_dir,
        refresh=refresh,
    )
    stock_scores = build_stock_leader_scores(
        sector_features=sector_features,
        constituents=constituents,
        stock_histories=stock_histories,
        start_date=start_date,
        lookback_days=lookback_days,
    )
    weights = build_sector_flow_target_weights(
        sector_features=sector_features,
        stock_scores=stock_scores,
        gross_exposure=gross_exposure,
        integer_percent=integer_percent,
        top_sectors=top_sectors,
        top_stocks_per_sector=top_stocks_per_sector,
    )
    market_data = _trim_market_data(stock_histories, start_date=start_date, end_date=end_date)

    sector_features.to_csv(output_dir / "sector_flow_features.csv", index=False, encoding="utf-8-sig")
    stock_scores.to_csv(output_dir / "stock_leader_scores.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(output_dir / "target_weights.csv", index=False, encoding="utf-8-sig")
    sector_features.to_csv(output_dir / "ha_premium_history.csv", index=False, encoding="utf-8-sig")
    _write_latest_snapshot(sector_features, output_dir / "last_premium_snapshot.csv")
    return SectorFlowBuildResult(
        sector_features=sector_features,
        stock_scores=stock_scores,
        weights=weights,
        market_data=market_data,
    )


def build_sector_features(
    histories: Sequence[pd.DataFrame],
    *,
    start_date: str,
    end_date: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    frames = []
    for history in histories:
        if history.empty:
            continue
        frame = history.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
        frame = frame.sort_values("date")
        frame["sector_return_20"] = frame["sector_close"] / frame["sector_close"].shift(lookback_days) - 1.0
        frame["sector_flow_5"] = frame["main_net_flow"].rolling(5, min_periods=3).sum()
        frame["sector_flow_20"] = frame["main_net_flow"].rolling(lookback_days, min_periods=max(5, lookback_days // 2)).sum()
        frame["sector_flow_accel"] = frame["sector_flow_5"] - frame["sector_flow_20"] / max(lookback_days / 5, 1)
        frame["sector_flow_pct_5"] = frame["main_net_flow_pct"].rolling(5, min_periods=3).mean()
        frames.append(frame)
    if not frames:
        return _empty_sector_features()

    result = pd.concat(frames, ignore_index=True)
    result = result[(result["date"] >= _parse_date(start_date)) & (result["date"] <= _parse_date(end_date))].copy()
    if result.empty:
        return _empty_sector_features()

    result["market_return_20"] = result.groupby("date")["sector_return_20"].transform("mean")
    result["sector_relative_strength"] = result["sector_return_20"] - result["market_return_20"]
    for source, target in [
        ("sector_flow_accel", "flow_accel_rank"),
        ("sector_flow_pct_5", "flow_pct_rank"),
        ("sector_relative_strength", "relative_strength_rank"),
    ]:
        result[target] = result.groupby("date")[source].rank(pct=True)
    result["sector_score"] = (
        result["flow_accel_rank"].fillna(0.0) * 0.4
        + result["flow_pct_rank"].fillna(0.0) * 0.3
        + result["relative_strength_rank"].fillna(0.0) * 0.3
    )
    result["sector_rank"] = result.groupby("date")["sector_score"].rank(method="first", ascending=False)
    return result.sort_values(["date", "sector_rank", "sector_name"]).reset_index(drop=True)


def select_sector_pool(sector_features: pd.DataFrame, sector_pool_size: int = SECTOR_POOL_SIZE) -> list[str]:
    if sector_features.empty:
        return []
    ranked = (
        sector_features.groupby("sector_name", as_index=False)["sector_score"]
        .mean()
        .sort_values("sector_score", ascending=False)
    )
    return ranked.head(max(int(sector_pool_size), 1))["sector_name"].tolist()


def build_stock_leader_scores(
    *,
    sector_features: pd.DataFrame,
    constituents: pd.DataFrame,
    stock_histories: dict[str, pd.DataFrame],
    start_date: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    if sector_features.empty or constituents.empty or not stock_histories:
        return _empty_stock_scores()

    stock_frames = []
    member_cols = ["sector_name", "symbol", "name"]
    members = constituents[member_cols].drop_duplicates().copy()
    for symbol, hist in stock_histories.items():
        if hist.empty:
            continue
        frame = hist.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
        frame = frame.sort_values("date")
        frame["stock_return_20"] = frame["close"] / frame["close"].shift(lookback_days) - 1.0
        frame["volume_ratio"] = frame["volume"].rolling(5, min_periods=3).mean() / frame["volume"].rolling(lookback_days, min_periods=max(5, lookback_days // 2)).mean()
        frame["symbol"] = symbol
        stock_frames.append(frame[["date", "symbol", "close", "volume", "stock_return_20", "volume_ratio"]])
    if not stock_frames:
        return _empty_stock_scores()

    stocks = pd.concat(stock_frames, ignore_index=True)
    stocks = stocks[stocks["date"] >= _parse_date(start_date)].copy()
    stocks = stocks.merge(members, on="symbol", how="inner")
    stocks = stocks.merge(
        sector_features[["date", "sector_name", "sector_return_20", "sector_score", "sector_rank"]],
        on=["date", "sector_name"],
        how="inner",
    )
    stocks["stock_relative_strength"] = stocks["stock_return_20"] - stocks["sector_return_20"]
    stocks = stocks[(stocks["stock_return_20"] > 0) & (stocks["stock_relative_strength"] > 0)].copy()
    if stocks.empty:
        return _empty_stock_scores()

    group = stocks.groupby(["date", "sector_name"])
    stocks["stock_rs_rank"] = group["stock_relative_strength"].rank(pct=True)
    stocks["volume_ratio_rank"] = group["volume_ratio"].rank(pct=True)
    stocks["stock_score"] = stocks["stock_rs_rank"].fillna(0.0) * 0.75 + stocks["volume_ratio_rank"].fillna(0.0) * 0.25
    return stocks.sort_values(["date", "sector_name", "stock_score"], ascending=[True, True, False]).reset_index(drop=True)


def build_sector_flow_target_weights(
    *,
    sector_features: pd.DataFrame,
    stock_scores: pd.DataFrame,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
    top_sectors: int = TOP_SECTORS,
    top_stocks_per_sector: int = TOP_STOCKS_PER_SECTOR,
) -> pd.DataFrame:
    if sector_features.empty or stock_scores.empty or gross_exposure <= 0:
        return _empty_weights()

    frames = []
    for date, sectors in sector_features.groupby("date", sort=True):
        selected_sectors = sectors[(sectors["sector_rank"] <= top_sectors) & (sectors["sector_score"] > MIN_SECTOR_SCORE)].copy()
        if selected_sectors.empty:
            continue
        selected_stocks = stock_scores[
            (stock_scores["date"] == date) & stock_scores["sector_name"].isin(selected_sectors["sector_name"])
        ].copy()
        if selected_stocks.empty:
            continue

        sector_score_total = float(selected_sectors["sector_score"].clip(lower=0).sum())
        if sector_score_total <= 0:
            continue
        sector_weights = dict(
            zip(
                selected_sectors["sector_name"],
                selected_sectors["sector_score"].clip(lower=0) / sector_score_total * gross_exposure,
            )
        )
        day_rows = []
        for sector_name, group in selected_stocks.groupby("sector_name", sort=False):
            leaders = group.sort_values("stock_score", ascending=False).head(top_stocks_per_sector).copy()
            score_total = float(leaders["stock_score"].clip(lower=0).sum())
            if leaders.empty or score_total <= 0:
                continue
            leaders["target_weight"] = leaders["stock_score"].clip(lower=0) / score_total * sector_weights[sector_name]
            day_rows.append(leaders)
        if not day_rows:
            continue
        day = pd.concat(day_rows, ignore_index=True)
        if integer_percent:
            day["target_weight"] = _largest_remainder_weights(day["target_weight"].tolist(), gross_exposure=float(day["target_weight"].sum()))
        day["premium_rate"] = day["sector_score"]
        frames.append(
            day[
                [
                    "date",
                    "symbol",
                    "name",
                    "target_weight",
                    "premium_rate",
                    "sector_name",
                    "sector_score",
                    "sector_rank",
                    "stock_score",
                    "stock_relative_strength",
                    "volume_ratio",
                ]
            ]
        )
    if not frames:
        return _empty_weights()
    return pd.concat(frames, ignore_index=True)


def normalize_sector_flow_history(flow: pd.DataFrame, price: pd.DataFrame, sector_name: str) -> pd.DataFrame:
    if flow.empty or price.empty:
        return pd.DataFrame()
    flow_date_col = _find_column(flow, ["date", "\u65e5\u671f"])
    main_flow_col = _find_column(flow, ["main_net_flow", "\u4e3b\u529b\u51c0\u6d41\u5165-\u51c0\u989d"])
    main_pct_col = _find_column(flow, ["main_net_flow_pct", "\u4e3b\u529b\u51c0\u6d41\u5165-\u51c0\u5360\u6bd4"])
    price_date_col = _find_column(price, ["date", "\u65e5\u671f"])
    close_col = _find_column(price, ["close", "\u6536\u76d8"])
    out_flow = pd.DataFrame(
        {
            "date": pd.to_datetime(flow[flow_date_col]).dt.tz_localize(None).dt.normalize(),
            "main_net_flow": _to_numeric(flow[main_flow_col]),
            "main_net_flow_pct": _to_numeric(flow[main_pct_col]),
        }
    )
    out_price = pd.DataFrame(
        {
            "date": pd.to_datetime(price[price_date_col]).dt.tz_localize(None).dt.normalize(),
            "sector_close": _to_numeric(price[close_col]),
        }
    )
    merged = out_flow.merge(out_price, on="date", how="inner")
    merged["sector_name"] = sector_name
    return merged.dropna(subset=["date", "sector_close"]).sort_values("date").reset_index(drop=True)


def _fetch_industry_names() -> list[str]:
    import akshare as ak

    df = ak.stock_board_industry_name_em()
    name_col = _find_column(df, ["\u677f\u5757\u540d\u79f0", "\u540d\u79f0", "name"])
    return [str(value) for value in df[name_col].dropna().tolist()]


def _fetch_sector_histories(sector_names: Iterable[str], start_date: str, end_date: str) -> list[pd.DataFrame]:
    import akshare as ak

    histories = []
    for sector_name in sector_names:
        try:
            flow = ak.stock_sector_fund_flow_hist(symbol=sector_name)
            price = ak.stock_board_industry_hist_em(symbol=sector_name, start_date=start_date, end_date=end_date, period="\u65e5k", adjust="")
            normalized = normalize_sector_flow_history(flow, price, sector_name)
            if not normalized.empty:
                histories.append(normalized)
        except Exception as exc:
            print(f"skip sector {sector_name}: {exc}")
    return histories


def _fetch_sector_constituents(sector_names: Sequence[str]) -> pd.DataFrame:
    import akshare as ak

    rows = []
    for sector_name in sector_names:
        try:
            df = ak.stock_board_industry_cons_em(symbol=sector_name)
        except Exception as exc:
            print(f"skip constituents for {sector_name}: {exc}")
            continue
        code_col = _find_column(df, ["\u4ee3\u7801", "code"])
        name_col = _find_column(df, ["\u540d\u79f0", "name"], required=False)
        for _, row in df.iterrows():
            symbol = normalize_a_share_trade_symbol(row[code_col])
            if not symbol.startswith(("SH", "SZ", "BJ")):
                continue
            rows.append(
                {
                    "sector_name": sector_name,
                    "symbol": symbol,
                    "name": str(row[name_col]) if name_col else symbol,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["sector_name", "symbol", "name"])
    return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)


def _fetch_stock_histories(
    *,
    symbols: Sequence[AShareSymbol],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    refresh: bool,
) -> dict[str, pd.DataFrame]:
    client = AkshareHistoryClient(cache_dir=cache_dir, refresh=refresh)
    histories = {}
    for symbol in symbols:
        hist = client.fetch_a_share_symbol(symbol, start_date, end_date)
        if hist.empty:
            continue
        histories[symbol.trade_symbol] = hist
    return histories


def _symbols_from_constituents(constituents: pd.DataFrame) -> list[AShareSymbol]:
    if constituents.empty:
        return []
    unique = constituents[["symbol", "name"]].drop_duplicates("symbol")
    return [AShareSymbol(code=row.symbol, name=row.name) for row in unique.itertuples(index=False)]


def _trim_market_data(stock_histories: dict[str, pd.DataFrame], *, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    out = {}
    for symbol, hist in stock_histories.items():
        frame = hist.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
        if frame.empty:
            continue
        frame["symbol"] = symbol
        out[symbol] = frame[["date", "open", "high", "low", "close", "volume", "symbol"]]
    return out


def _write_latest_snapshot(frame: pd.DataFrame, path: Path) -> None:
    if frame.empty or "date" not in frame:
        frame.head(0).to_csv(path, index=False, encoding="utf-8-sig")
        return
    latest_date = frame["date"].max()
    frame[frame["date"] == latest_date].to_csv(path, index=False, encoding="utf-8-sig")


def _largest_remainder_weights(weights: list[float], gross_exposure: float) -> list[float]:
    if gross_exposure <= 0:
        return [0.0 for _ in weights]
    basis = 100
    raw = [w / gross_exposure * basis for w in weights]
    floors = [int(x) for x in raw]
    remaining = max(basis - sum(floors), 0)
    fractions = sorted(enumerate(raw), key=lambda item: item[1] - int(item[1]), reverse=True)
    for idx, _ in fractions[:remaining]:
        floors[idx] += 1
    return [value / basis * gross_exposure for value in floors]


def _lookback_start_date(start_date: str, lookback_days: int) -> str:
    start = _parse_date(start_date)
    return (start - pd.Timedelta(days=max(lookback_days * 4, 0))).strftime("%Y%m%d")


def _parse_date(value: object) -> pd.Timestamp:
    return pd.to_datetime(value).tz_localize(None).normalize()


def _find_column(df: pd.DataFrame, names: Sequence[str], required: bool = True) -> str | None:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for name in names:
        key = name.strip().lower()
        if key in lower_map:
            return lower_map[key]
    if required:
        raise ValueError(f"Cannot find any of columns {list(names)} in {list(df.columns)}")
    return None


def _to_numeric(series: object) -> pd.Series:
    return pd.to_numeric(pd.Series(series).astype(str).str.replace(",", "", regex=False), errors="coerce")


def _empty_sector_features() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "sector_name",
            "sector_close",
            "main_net_flow",
            "main_net_flow_pct",
            "sector_return_20",
            "sector_flow_5",
            "sector_flow_20",
            "sector_flow_accel",
            "sector_flow_pct_5",
            "market_return_20",
            "sector_relative_strength",
            "sector_score",
            "sector_rank",
        ]
    )


def _empty_stock_scores() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "symbol",
            "name",
            "sector_name",
            "close",
            "volume",
            "stock_return_20",
            "volume_ratio",
            "sector_return_20",
            "sector_score",
            "sector_rank",
            "stock_relative_strength",
            "stock_score",
        ]
    )


def _empty_weights() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "symbol",
            "name",
            "target_weight",
            "premium_rate",
            "sector_name",
            "sector_score",
            "sector_rank",
            "stock_score",
            "stock_relative_strength",
            "volume_ratio",
        ]
    )
