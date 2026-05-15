"""Local CSV provider used as an explicit fallback for Phase 1a-7."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from ashare.ingest.contracts import normalize_index_code, normalize_stock_code
from ashare.ingest.providers import ProviderError
from ashare.pit.effective_date import calculate_effective_date


TARGET_CSV_FILES: tuple[str, ...] = (
    "trading_calendar.csv",
    "securities.csv",
    "universe_members.csv",
    "daily_prices.csv",
    "valuation_daily.csv",
)


class CsvFallbackProvider:
    """Provider backed by the five Phase 1a-7 target CSV files."""

    name = "csv"
    provider_version_or_unknown = "csv-local"

    def __init__(self, csv_dir: str | Path) -> None:
        self.csv_dir = Path(csv_dir)
        self._validate_target_files()

    def fetch_trading_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        frame = self._read_csv("trading_calendar")
        if "trade_date" not in frame.columns:
            raise ProviderError("trading_calendar.csv missing trade_date.")
        dates = _date_series(frame["trade_date"])
        return frame.loc[(dates >= start_date) & (dates <= end_date)].reset_index(drop=True)

    def fetch_index_members(self, index_code: str, as_of_date: date) -> pd.DataFrame:
        frame = self._read_csv("universe_members")
        if "index_code" not in frame.columns:
            raise ProviderError("universe_members.csv missing index_code.")
        normalized_index = normalize_index_code(index_code)
        index_values = frame["index_code"].map(normalize_index_code)
        frame = frame.loc[index_values == normalized_index].copy()
        if frame.empty:
            raise ProviderError(f"universe_members.csv has no rows for index_code={index_code}.")
        return self._fill_universe_effective_dates(frame)

    def fetch_securities(self, stock_codes: Sequence[str], as_of_date: date) -> pd.DataFrame:
        frame = self._read_csv("securities")
        if "stock_code" not in frame.columns:
            raise ProviderError("securities.csv missing stock_code.")
        requested = {normalize_stock_code(code) for code in stock_codes}
        requested.discard(None)
        stock_values = frame["stock_code"].map(normalize_stock_code)
        frame = frame.loc[stock_values.isin(requested)].copy()
        if frame.empty:
            raise ProviderError("securities.csv has no rows for requested stock codes.")
        return self._fill_securities_effective_dates(frame)

    def fetch_daily_prices(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        frame = self._read_csv("daily_prices")
        for column in ["stock_code", "trade_date"]:
            if column not in frame.columns:
                raise ProviderError(f"daily_prices.csv missing {column}.")
        requested = {normalize_stock_code(code) for code in stock_codes}
        requested.discard(None)
        dates = _date_series(frame["trade_date"])
        stock_values = frame["stock_code"].map(normalize_stock_code)
        return frame.loc[
            stock_values.isin(requested) & (dates >= start_date) & (dates <= end_date)
        ].reset_index(drop=True)

    def fetch_valuation_daily(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        frame = self._read_csv("valuation_daily")
        for column in ["stock_code", "trade_date"]:
            if column not in frame.columns:
                raise ProviderError(f"valuation_daily.csv missing {column}.")
        requested = {normalize_stock_code(code) for code in stock_codes}
        requested.discard(None)
        dates = _date_series(frame["trade_date"])
        stock_values = frame["stock_code"].map(normalize_stock_code)
        return frame.loc[
            stock_values.isin(requested) & (dates >= start_date) & (dates <= end_date)
        ].reset_index(drop=True)

    def _validate_target_files(self) -> None:
        missing = [name for name in TARGET_CSV_FILES if not (self.csv_dir / name).is_file()]
        if missing:
            joined = ", ".join(missing)
            raise FileNotFoundError(f"Missing Phase 1a-7 CSV fallback file(s): {joined}")

    def _read_csv(self, dataset: str) -> pd.DataFrame:
        path = self.csv_dir / f"{dataset}.csv"
        return pd.read_csv(path)

    def _open_trading_days(self) -> list[date]:
        calendar = self._read_csv("trading_calendar")
        if "trade_date" not in calendar.columns:
            raise ProviderError("trading_calendar.csv missing trade_date.")
        if "is_open" in calendar.columns:
            is_open = calendar["is_open"].map(_to_bool).fillna(False)
        else:
            is_open = pd.Series(True, index=calendar.index)
        return sorted(_date_series(calendar.loc[is_open, "trade_date"]).tolist())

    def _fill_universe_effective_dates(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        trading_days = self._open_trading_days()
        for effective_column, publish_column, fallback_column in [
            ("in_effective_date", "in_publish_time", "in_date"),
            ("out_effective_date", "out_publish_time", "out_date"),
        ]:
            if effective_column not in result.columns:
                result[effective_column] = pd.NA
            if publish_column not in result.columns:
                result[publish_column] = pd.NA
            mask = result[effective_column].isna() | (
                result[effective_column].astype("string").str.strip() == ""
            )
            publish_mask = mask & result[publish_column].notna() & (
                result[publish_column].astype("string").str.strip() != ""
            )
            result.loc[publish_mask, effective_column] = result.loc[publish_mask, publish_column].map(
                lambda value: calculate_effective_date(pd.to_datetime(value).to_pydatetime(), trading_days)
            )
            fallback_mask = mask & ~publish_mask
            if fallback_column in result.columns:
                result.loc[fallback_mask, effective_column] = result.loc[
                    fallback_mask, fallback_column
                ]
        return result

    def _fill_securities_effective_dates(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        effective_column = "delist_effective_date"
        publish_column = "delist_publish_time"
        fallback_column = "delist_date"
        for column in [effective_column, publish_column, fallback_column]:
            if column not in result.columns:
                result[column] = pd.NA
        mask = result[effective_column].isna() | (
            result[effective_column].astype("string").str.strip() == ""
        )
        publish_mask = mask & result[publish_column].notna() & (
            result[publish_column].astype("string").str.strip() != ""
        )
        if bool(publish_mask.any()):
            trading_days = self._open_trading_days()
            result.loc[publish_mask, effective_column] = result.loc[
                publish_mask, publish_column
            ].map(lambda value: calculate_effective_date(pd.to_datetime(value).to_pydatetime(), trading_days))
        fallback_mask = mask & ~publish_mask
        result.loc[fallback_mask, effective_column] = result.loc[fallback_mask, fallback_column]
        return result


def _date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="raise").dt.date


def _to_bool(value: object) -> bool | None:
    if value is None or value is pd.NA:
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y"}:
        return True
    if raw in {"false", "0", "no", "n"}:
        return False
    return None
