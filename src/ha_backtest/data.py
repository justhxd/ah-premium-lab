from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

import pandas as pd


DATE_FMT = "%Y%m%d"
A_SHARE_ANNUAL_MA_WINDOW = 250


@dataclass(frozen=True)
class AHPair:
    name: str
    a_code: str
    h_code: str

    @property
    def a_symbol(self) -> str:
        code = self.a_code.strip().lower()
        if code.startswith(("sh", "sz", "bj")):
            return code[2:]
        return code

    @property
    def h_symbol(self) -> str:
        return self.h_code.strip().upper().replace("HK", "").zfill(5)

    @property
    def a_trade_symbol(self) -> str:
        return self.a_code.strip().upper()

    @property
    def trade_symbol(self) -> str:
        return f"HK{self.h_symbol}"


def load_ah_pairs(path: Path) -> List[AHPair]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return _load_pairs_json(path)
    return _load_pairs_csv(path)


def _load_pairs_json(path: Path) -> List[AHPair]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    pairs: List[AHPair] = []
    for h_code, info in data.items():
        a_code = str(info.get("a_code", "")).upper()
        if not a_code:
            continue
        pairs.append(
            AHPair(
                name=str(info.get("name") or h_code),
                a_code=a_code,
                h_code=str(h_code).zfill(5),
            )
        )
    return pairs


def _load_pairs_csv(path: Path) -> List[AHPair]:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    name_col = _find_column(df, ["name", "\u540d\u79f0", "\u80a1\u7968\u540d\u79f0"], required=False)
    a_col = _find_column(df, ["a_code", "A\u80a1\u4ee3\u7801", "A\u80a1\u4ee3\u78bc", "A_CODE"])
    h_col = _find_column(df, ["h_code", "H\u80a1\u4ee3\u7801", "H\u80a1\u4ee3\u78bc", "H_CODE"])

    pairs: List[AHPair] = []
    for _, row in df.iterrows():
        a_code = str(row[a_col]).strip().upper()
        h_code = str(row[h_col]).strip().upper().replace("HK", "").zfill(5)
        if not a_code or not h_code:
            continue
        name = str(row[name_col]).strip() if name_col else h_code
        pairs.append(AHPair(name=name or h_code, a_code=a_code, h_code=h_code))
    return pairs


def build_ha_premium_history(
    pairs: Sequence[AHPair],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    refresh: bool = False,
    fx_csv: Optional[Path] = None,
    annual_ma_window: int = A_SHARE_ANNUAL_MA_WINDOW,
) -> pd.DataFrame:
    client = AkshareHistoryClient(cache_dir=Path(cache_dir), refresh=refresh)
    fx = read_fx_history(fx_csv) if fx_csv else client.fetch_hkd_cny(start_date, end_date)
    a_start_date = _lookback_start_date(start_date, annual_ma_window)

    rows: List[pd.DataFrame] = []
    for pair in pairs:
        a_hist = client.fetch_a_share(pair, a_start_date, end_date)
        h_hist = client.fetch_h_share(pair, start_date, end_date)
        merged = _merge_pair_history(
            pair,
            a_hist,
            h_hist,
            fx,
            start_date=start_date,
            annual_ma_window=annual_ma_window,
        )
        if not merged.empty:
            rows.append(merged)

    if not rows:
        return _empty_premium_frame()

    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(["date", "h_code"]).reset_index(drop=True)


def build_target_weights(
    premium_df: pd.DataFrame,
    min_premium: float = 0.0,
    gross_exposure: float = 1.0,
    integer_percent: bool = False,
    annual_line_filter: bool = True,
) -> pd.DataFrame:
    from .strategies.ha_premium.weights import build_target_weights as _build_target_weights

    return _build_target_weights(
        premium_df,
        min_premium=min_premium,
        gross_exposure=gross_exposure,
        integer_percent=integer_percent,
        annual_line_filter=annual_line_filter,
    )

def build_a_share_market_data(
    pairs: Sequence[AHPair],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    client = AkshareHistoryClient(cache_dir=Path(cache_dir), refresh=refresh)
    data: dict[str, pd.DataFrame] = {}
    for pair in pairs:
        hist = client.fetch_a_share(pair, start_date, end_date)
        if hist.empty:
            continue
        hist = hist.copy()
        hist["symbol"] = pair.a_trade_symbol
        data[pair.a_trade_symbol] = hist[["date", "open", "high", "low", "close", "volume", "symbol"]]
    return data


def build_h_share_market_data(
    pairs: Sequence[AHPair],
    start_date: str,
    end_date: str,
    cache_dir: Path,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    client = AkshareHistoryClient(cache_dir=Path(cache_dir), refresh=refresh)
    data: dict[str, pd.DataFrame] = {}
    for pair in pairs:
        hist = client.fetch_h_share(pair, start_date, end_date)
        if hist.empty:
            continue
        hist = hist.copy()
        hist["symbol"] = pair.trade_symbol
        data[pair.trade_symbol] = hist[["date", "open", "high", "low", "close", "volume", "symbol"]]
    return data


class AkshareHistoryClient:
    def __init__(self, cache_dir: Path, refresh: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.refresh = refresh
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "market_cache.sqlite"
        self._init_db()

    def fetch_a_share(self, pair: AHPair, start_date: str, end_date: str) -> pd.DataFrame:
        def fetch(range_start: str, range_end: str) -> pd.DataFrame:
            import akshare as ak

            try:
                df = ak.stock_zh_a_hist(
                    symbol=pair.a_symbol,
                    period="daily",
                    start_date=range_start,
                    end_date=range_end,
                    adjust="",
                )
            except Exception as exc:
                print(f"stock_zh_a_hist failed for {pair.a_code}; fallback to stock_zh_a_daily: {exc}")
                df = ak.stock_zh_a_daily(
                    symbol=pair.a_code.lower(),
                    start_date=range_start,
                    end_date=range_end,
                    adjust="",
                )
            return normalize_ohlcv(df, pair.a_trade_symbol)

        return self._cached_ohlcv(
            market="a",
            symbol=pair.a_symbol,
            trade_symbol=pair.a_trade_symbol,
            start_date=start_date,
            end_date=end_date,
            fetch=fetch,
            empty_on_failure=True,
        )

    def fetch_h_share(self, pair: AHPair, start_date: str, end_date: str) -> pd.DataFrame:
        def fetch(range_start: str, range_end: str) -> pd.DataFrame:
            import akshare as ak

            try:
                df = ak.stock_hk_hist(
                    symbol=pair.h_symbol,
                    period="daily",
                    start_date=range_start,
                    end_date=range_end,
                    adjust="",
                )
            except Exception as exc:
                print(f"stock_hk_hist failed for {pair.h_code}; fallback to stock_hk_daily: {exc}")
                df = ak.stock_hk_daily(symbol=pair.h_symbol, adjust="")
            out = normalize_ohlcv(df, pair.trade_symbol)
            start = pd.to_datetime(range_start)
            end = pd.to_datetime(range_end)
            return out[(out["date"] >= start) & (out["date"] <= end)].reset_index(drop=True)

        return self._cached_ohlcv(
            market="h",
            symbol=pair.h_symbol,
            trade_symbol=pair.trade_symbol,
            start_date=start_date,
            end_date=end_date,
            fetch=fetch,
            empty_on_failure=True,
        )

    def fetch_hkd_cny(self, start_date: str, end_date: str) -> pd.DataFrame:
        def fetch(range_start: str, range_end: str) -> pd.DataFrame:
            import akshare as ak

            df = ak.currency_boc_sina(symbol="\u6e2f\u5e01", start_date=range_start, end_date=range_end)
            return normalize_fx(df)

        return self._cached_fx(start_date=start_date, end_date=end_date, fetch=fetch)

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv (
                    market TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    trade_symbol TEXT NOT NULL,
                    PRIMARY KEY (market, symbol, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fx_rates (
                    pair TEXT NOT NULL,
                    date TEXT NOT NULL,
                    hkd_cny REAL NOT NULL,
                    PRIMARY KEY (pair, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_coverage (
                    kind TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    PRIMARY KEY (kind, cache_key, start_date, end_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup ON ohlcv (market, symbol, date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fx_lookup ON fx_rates (pair, date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_coverage_lookup ON cache_coverage (kind, cache_key, start_date, end_date)")

    def _cached_ohlcv(
        self,
        market: str,
        symbol: str,
        trade_symbol: str,
        start_date: str,
        end_date: str,
        fetch: Callable[[str, str], pd.DataFrame],
        empty_on_failure: bool,
    ) -> pd.DataFrame:
        ranges = [(start_date, end_date)] if self.refresh else self._missing_ranges_ohlcv(market, symbol, start_date, end_date)

        for range_start, range_end in ranges:
            label = f"{market}_{symbol}_{range_start}_{range_end}"
            fetched = self._fetch_with_retries(label, lambda: fetch(range_start, range_end), empty_on_failure)
            if not fetched.empty:
                self._upsert_ohlcv(market, symbol, trade_symbol, fetched)
            if not fetched.attrs.get("fetch_failed"):
                self._mark_coverage("ohlcv", f"{market}:{symbol}", range_start, range_end)

        return self._query_ohlcv(market, symbol, start_date, end_date)

    def _cached_fx(
        self,
        start_date: str,
        end_date: str,
        fetch: Callable[[str, str], pd.DataFrame],
    ) -> pd.DataFrame:
        pair = "HKD/CNY"
        ranges = [(start_date, end_date)] if self.refresh else self._missing_ranges_fx(pair, start_date, end_date)

        for range_start, range_end in ranges:
            label = f"fx_hkd_cny_{range_start}_{range_end}"
            fetched = self._fetch_with_retries(label, lambda: fetch(range_start, range_end), empty_on_failure=False)
            if not fetched.empty:
                self._upsert_fx(pair, fetched)
            self._mark_coverage("fx", pair, range_start, range_end)

        return self._query_fx(pair, start_date, end_date)

    def _fetch_with_retries(
        self,
        label: str,
        fetch: Callable[[], pd.DataFrame],
        empty_on_failure: bool,
    ) -> pd.DataFrame:
        label_parts = label.split("_")
        if _parse_date(label_parts[-2]) > _parse_date(label_parts[-1]):
            return pd.DataFrame()

        delays = [1.0, 2.0, 5.0, 10.0]
        last_error: Optional[Exception] = None
        for attempt, delay in enumerate([0.0] + delays, start=1):
            if delay:
                time.sleep(delay)
            try:
                return fetch()
            except Exception as exc:
                last_error = exc
                print(f"fetch failed for {label} (attempt {attempt}/{len(delays) + 1}): {exc}")
        if empty_on_failure:
            print(f"skip {label} after repeated fetch failures")
            failed = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "symbol"])
            failed.attrs["fetch_failed"] = True
            return failed
        assert last_error is not None
        raise last_error

    def _missing_ranges_ohlcv(self, market: str, symbol: str, start_date: str, end_date: str) -> list[tuple[str, str]]:
        coverage = self._coverage_ranges("ohlcv", f"{market}:{symbol}")
        if not coverage:
            bounds = self._date_bounds_ohlcv(market, symbol)
            coverage = [bounds] if bounds else []
        return self._missing_ranges(coverage, start_date, end_date)

    def _missing_ranges_fx(self, pair: str, start_date: str, end_date: str) -> list[tuple[str, str]]:
        coverage = self._coverage_ranges("fx", pair)
        if not coverage:
            bounds = self._date_bounds_fx(pair)
            coverage = [bounds] if bounds else []
        return self._missing_ranges(coverage, start_date, end_date)

    def _missing_ranges(
        self,
        coverage: Sequence[tuple[pd.Timestamp, pd.Timestamp]],
        start_date: str,
        end_date: str,
    ) -> list[tuple[str, str]]:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if not coverage:
            return [(start_date, end_date)]

        cursor = start
        ranges: list[tuple[str, str]] = []
        for covered_start, covered_end in sorted(coverage):
            if covered_end < cursor:
                continue
            if covered_start > end:
                break
            if cursor < covered_start:
                ranges.append((_format_date(cursor), _format_date(covered_start - pd.Timedelta(days=1))))
            if covered_end >= cursor:
                cursor = covered_end + pd.Timedelta(days=1)
            if cursor > end:
                break
        if cursor <= end:
            ranges.append((_format_date(cursor), _format_date(end)))
        return ranges

    def _date_bounds_ohlcv(self, market: str, symbol: str) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM ohlcv WHERE market = ? AND symbol = ?",
                (market, symbol),
            ).fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return pd.Timestamp(row[0]), pd.Timestamp(row[1])

    def _date_bounds_fx(self, pair: str) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM fx_rates WHERE pair = ?",
                (pair,),
            ).fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return pd.Timestamp(row[0]), pd.Timestamp(row[1])


    def _coverage_ranges(self, kind: str, cache_key: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT start_date, end_date
                FROM cache_coverage
                WHERE kind = ? AND cache_key = ?
                ORDER BY start_date, end_date
                """,
                (kind, cache_key),
            ).fetchall()
        return [(pd.Timestamp(start), pd.Timestamp(end)) for start, end in rows]

    def _mark_coverage(self, kind: str, cache_key: str, start_date: object, end_date: object) -> None:
        start = _date_key(start_date)
        end = _date_key(end_date)
        if start > end:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_coverage (kind, cache_key, start_date, end_date)
                VALUES (?, ?, ?, ?)
                """,
                (kind, cache_key, start, end),
            )

    def _query_ohlcv(self, market: str, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT date, open, high, low, close, volume, trade_symbol AS symbol
                FROM ohlcv
                WHERE market = ? AND symbol = ? AND date BETWEEN ? AND ?
                ORDER BY date
                """,
                conn,
                params=(market, symbol, _date_key(start_date), _date_key(end_date)),
                parse_dates=["date"],
            )
        if df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "symbol"])
        return df

    def _query_fx(self, pair: str, start_date: str, end_date: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT date, hkd_cny
                FROM fx_rates
                WHERE pair = ? AND date BETWEEN ? AND ?
                ORDER BY date
                """,
                conn,
                params=(pair, _date_key(start_date), _date_key(end_date)),
                parse_dates=["date"],
            )
        if df.empty:
            return pd.DataFrame(columns=["date", "hkd_cny"])
        return df

    def _upsert_ohlcv(self, market: str, symbol: str, trade_symbol: str, df: pd.DataFrame) -> None:
        frame = normalize_ohlcv(df, trade_symbol)
        if frame.empty:
            return
        records = [
            (
                market,
                symbol,
                _date_key(date),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                trade_symbol,
            )
            for date, row in frame.set_index("date").iterrows()
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO ohlcv
                    (market, symbol, date, open, high, low, close, volume, trade_symbol)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        self._mark_coverage("ohlcv", f"{market}:{symbol}", frame["date"].min(), frame["date"].max())

    def _upsert_fx(self, pair: str, df: pd.DataFrame) -> None:
        frame = normalize_fx(df)
        if frame.empty:
            return
        records = [(pair, _date_key(row.date), float(row.hkd_cny)) for row in frame.itertuples(index=False)]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fx_rates (pair, date, hkd_cny) VALUES (?, ?, ?)",
                records,
            )
        self._mark_coverage("fx", pair, frame["date"].min(), frame["date"].max())

def read_fx_history(path: Path) -> pd.DataFrame:
    return normalize_fx(pd.read_csv(path, encoding="utf-8-sig"))


def normalize_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "symbol"])

    date_col = _find_column(df, ["date", "\u65e5\u671f", "\u65f6\u95f4"])
    open_col = _find_column(df, ["open", "\u5f00\u76d8"])
    high_col = _find_column(df, ["high", "\u6700\u9ad8"])
    low_col = _find_column(df, ["low", "\u6700\u4f4e"])
    close_col = _find_column(df, ["close", "\u6536\u76d8"])
    volume_col = _find_column(df, ["volume", "\u6210\u4ea4\u91cf"], required=False)

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col]).dt.tz_localize(None),
            "open": _to_numeric(df[open_col]),
            "high": _to_numeric(df[high_col]),
            "low": _to_numeric(df[low_col]),
            "close": _to_numeric(df[close_col]),
            "volume": _to_numeric(df[volume_col]) if volume_col else 0.0,
            "symbol": symbol,
        }
    )
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def normalize_fx(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "hkd_cny"])

    date_col = _find_column(df, ["date", "\u65e5\u671f", "\u65f6\u95f4"])
    rate_col = _find_rate_column(df, exclude=[date_col])

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col]).dt.tz_localize(None),
            "hkd_cny": _to_numeric(df[rate_col]),
        }
    )
    median = out["hkd_cny"].dropna().median()
    if pd.notna(median) and median > 10:
        out["hkd_cny"] = out["hkd_cny"] / 100.0
    return out.dropna().sort_values("date").reset_index(drop=True)


def _merge_pair_history(
    pair: AHPair,
    a_hist: pd.DataFrame,
    h_hist: pd.DataFrame,
    fx: pd.DataFrame,
    start_date: Optional[str] = None,
    annual_ma_window: int = A_SHARE_ANNUAL_MA_WINDOW,
) -> pd.DataFrame:
    if a_hist.empty or h_hist.empty or fx.empty:
        return _empty_premium_frame()

    a = a_hist[["date", "close"]].rename(columns={"close": "a_close"})
    h = h_hist[["date", "close"]].rename(columns={"close": "h_close_hkd"})
    a["date"] = pd.to_datetime(a["date"]).astype("datetime64[ns]")
    h["date"] = pd.to_datetime(h["date"]).astype("datetime64[ns]")
    a = a.sort_values("date")
    a["a_ma250"] = (
        a["a_close"]
        .rolling(window=annual_ma_window, min_periods=annual_ma_window)
        .mean()
    )
    fx = fx.copy()
    fx["date"] = pd.to_datetime(fx["date"]).astype("datetime64[ns]")
    merged = pd.merge(a, h, on="date", how="inner").sort_values("date")
    if merged.empty:
        return _empty_premium_frame()

    merged = pd.merge_asof(
        merged,
        fx[["date", "hkd_cny"]].sort_values("date"),
        on="date",
        direction="backward",
    )
    merged["hkd_cny"] = merged["hkd_cny"].ffill().bfill()
    merged = merged.dropna(subset=["a_close", "h_close_hkd", "hkd_cny"])
    merged = merged[merged["a_close"] > 0].copy()
    if start_date:
        merged = merged[merged["date"] >= _parse_date(start_date)].copy()
    if merged.empty:
        return _empty_premium_frame()

    merged["h_close_cny"] = merged["h_close_hkd"] * merged["hkd_cny"]
    merged["premium_rate"] = (merged["h_close_cny"] / merged["a_close"] - 1.0) * 100.0
    merged["name"] = pair.name
    merged["a_code"] = pair.a_code.upper()
    merged["h_code"] = pair.h_symbol
    merged["trade_symbol"] = pair.trade_symbol
    return merged[
        [
            "date",
            "name",
            "a_code",
            "h_code",
            "trade_symbol",
            "a_close",
            "a_ma250",
            "h_close_hkd",
            "hkd_cny",
            "h_close_cny",
            "premium_rate",
        ]
    ]


def _largest_remainder_weights(weights: List[float], gross_exposure: float) -> List[float]:
    basis = 100
    raw = [w / gross_exposure * basis for w in weights]
    floors = [int(x) for x in raw]
    remaining = basis - sum(floors)
    fractions = sorted(enumerate(raw), key=lambda item: item[1] - int(item[1]), reverse=True)
    for idx, _ in fractions[:remaining]:
        floors[idx] += 1
    return [value / basis * gross_exposure for value in floors]


def _find_column(df: pd.DataFrame, names: Iterable[str], required: bool = True) -> Optional[str]:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for name in names:
        key = name.strip().lower()
        if key in lower_map:
            return lower_map[key]
    if required:
        raise ValueError(f"Cannot find any of columns {list(names)} in {list(df.columns)}")
    return None


def _find_rate_column(df: pd.DataFrame, exclude: Sequence[str]) -> str:
    preferred = ["hkd_cny", "\u4e2d\u95f4\u4ef7", "\u6c47\u5356\u4ef7", "\u73b0\u6c47\u5356\u51fa\u4ef7", "close", "rate", "price"]
    excluded = set(exclude)
    for name in preferred:
        col = _find_column(df.drop(columns=list(excluded), errors="ignore"), [name], required=False)
        if col:
            return col

    numeric_cols = []
    for col in df.columns:
        if col in excluded:
            continue
        series = _to_numeric(df[col])
        if series.notna().any():
            numeric_cols.append(col)
    if not numeric_cols:
        raise ValueError(f"Cannot find numeric FX rate column in {list(df.columns)}")
    return numeric_cols[0]




def _parse_date(value: object) -> pd.Timestamp:
    return pd.to_datetime(value).tz_localize(None).normalize()


def _format_date(value: pd.Timestamp) -> str:
    return value.strftime(DATE_FMT)


def _lookback_start_date(start_date: str, window: int) -> str:
    start = _parse_date(start_date)
    return _format_date(start - pd.Timedelta(days=max(window * 2, 0)))


def _date_key(value: object) -> str:
    return _parse_date(value).strftime("%Y-%m-%d")


def _to_numeric(series: object) -> pd.Series:
    return pd.to_numeric(pd.Series(series).astype(str).str.replace(",", "", regex=False), errors="coerce")


def _empty_premium_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "name",
            "a_code",
            "h_code",
            "trade_symbol",
            "a_close",
            "a_ma250",
            "h_close_hkd",
            "hkd_cny",
            "h_close_cny",
            "premium_rate",
        ]
    )







