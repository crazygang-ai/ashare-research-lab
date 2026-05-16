"""Auditable historical index-member import for PIT universes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ashare.ingest.contracts import normalize_index_code, normalize_stock_code
from ashare.storage.db import connect, init_db


REQUIRED_COLUMNS = [
    "index_code",
    "stock_code",
    "in_date",
    "out_date",
    "in_publish_time",
    "in_effective_date",
    "out_publish_time",
    "out_effective_date",
    "source",
    "source_tag",
]

INSERT_COLUMNS = [
    "index_code",
    "stock_code",
    "in_date",
    "out_date",
    "in_publish_time",
    "in_effective_date",
    "out_publish_time",
    "out_effective_date",
    "source",
    "source_tag",
    "universe_kind",
]


@dataclass(frozen=True)
class IndexMemberImportResult:
    db_path: Path
    input_path: Path
    row_count: int
    index_codes: tuple[str, ...]
    source_tags: tuple[str, ...]
    universe_kind: str


def import_index_members(
    *,
    input_path: str | Path,
    db_path: str | Path,
    universe_kind: str = "historical_pit",
    overwrite: bool = False,
) -> IndexMemberImportResult:
    """Import validated historical index membership CSV/Parquet into ``universe_members``."""
    if universe_kind not in {"historical_pit", "current_snapshot"}:
        raise ValueError("universe_kind must be historical_pit or current_snapshot.")
    path = Path(input_path)
    frame = _read_input(path)
    normalized = _normalize(frame, universe_kind=universe_kind)
    _validate_members(normalized)

    init_db(db_path)
    connection = connect(db_path)
    try:
        connection.execute("BEGIN TRANSACTION")
        try:
            if overwrite:
                _delete_existing_ranges(connection, normalized)
            else:
                _fail_on_existing_rows(connection, normalized)
            connection.register("_index_member_import", normalized.loc[:, INSERT_COLUMNS])
            try:
                column_sql = ", ".join(INSERT_COLUMNS)
                connection.execute(
                    f"""
                    INSERT INTO universe_members ({column_sql})
                    SELECT {column_sql} FROM _index_member_import
                    """
                )
            finally:
                connection.unregister("_index_member_import")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()

    return IndexMemberImportResult(
        db_path=Path(db_path),
        input_path=path,
        row_count=int(len(normalized)),
        index_codes=tuple(sorted(normalized["index_code"].unique().tolist())),
        source_tags=tuple(sorted(normalized["source_tag"].unique().tolist())),
        universe_kind=universe_kind,
    )


def _read_input(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Index member input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError("Index member input must be CSV or Parquet.")


def _normalize(frame: pd.DataFrame, *, universe_kind: str) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("Index member input missing required columns: " + ", ".join(missing))
    result = frame.copy()
    result["index_code"] = result["index_code"].map(normalize_index_code)
    result["stock_code"] = result["stock_code"].map(normalize_stock_code)
    for column in ["in_date", "out_date", "in_effective_date", "out_effective_date"]:
        result[column] = _date_series(result[column], column)
    for column in ["in_publish_time", "out_publish_time"]:
        result[column] = _timestamp_series(result[column], column)
    for column in ["source", "source_tag"]:
        result[column] = result[column].astype("string").str.strip()
        result.loc[result[column].eq(""), column] = pd.NA
    result["universe_kind"] = universe_kind
    return result.loc[:, INSERT_COLUMNS].copy()


def _validate_members(frame: pd.DataFrame) -> None:
    missing_required = {
        column: int(frame[column].isna().sum())
        for column in ["index_code", "stock_code", "in_date", "in_effective_date", "source", "source_tag"]
    }
    missing = {column: count for column, count in missing_required.items() if count}
    if missing:
        raise ValueError(f"Index member input has missing required values: {missing}")
    bad_out = frame["out_effective_date"].notna() & (
        frame["out_effective_date"] <= frame["in_effective_date"]
    )
    if bool(bad_out.any()):
        raise ValueError("out_effective_date must be after in_effective_date.")
    duplicate_keys = frame.duplicated(
        ["source_tag", "index_code", "stock_code", "in_effective_date"],
        keep=False,
    )
    if bool(duplicate_keys.any()):
        raise ValueError("Index member input contains duplicate member effective-date keys.")
    _fail_on_overlapping_intervals(frame)


def _fail_on_overlapping_intervals(frame: pd.DataFrame) -> None:
    for key, group in frame.groupby(["source_tag", "index_code", "stock_code"], dropna=False):
        sorted_group = group.sort_values("in_effective_date", kind="mergesort")
        previous_out: date | None = None
        previous_in: date | None = None
        for row in sorted_group.itertuples(index=False):
            current_in = _to_date(row.in_effective_date)
            if previous_out is None and previous_in is not None:
                raise ValueError(f"Open-ended overlapping index member interval for {key}.")
            if previous_out is not None and current_in < previous_out:
                raise ValueError(f"Overlapping index member intervals for {key}.")
            previous_out = _to_date(row.out_effective_date) if pd.notna(row.out_effective_date) else None
            previous_in = current_in


def _delete_existing_ranges(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
) -> None:
    keys = frame.loc[:, ["source_tag", "index_code"]].drop_duplicates()
    for row in keys.itertuples(index=False):
        connection.execute(
            "DELETE FROM universe_members WHERE source_tag = ? AND index_code = ?",
            [row.source_tag, row.index_code],
        )


def _fail_on_existing_rows(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
) -> None:
    keys = frame.loc[:, ["source_tag", "index_code"]].drop_duplicates()
    for row in keys.itertuples(index=False):
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM universe_members WHERE source_tag = ? AND index_code = ?",
                [row.source_tag, row.index_code],
            ).fetchone()[0]
        )
        if count:
            raise ValueError(
                "universe_members already contains rows for "
                f"source_tag={row.source_tag}, index_code={row.index_code}; use overwrite."
            )


def _date_series(series: pd.Series, column: str) -> pd.Series:
    mask = series.notna() & (series.astype("string").str.strip() != "")
    parsed = pd.to_datetime(series, errors="coerce")
    if bool((mask & parsed.isna()).any()):
        raise ValueError(f"{column} contains unparseable dates.")
    return parsed.dt.date.where(mask, None)


def _timestamp_series(series: pd.Series, column: str) -> pd.Series:
    mask = series.notna() & (series.astype("string").str.strip() != "")
    parsed = pd.to_datetime(series, errors="coerce")
    if bool((mask & parsed.isna()).any()):
        raise ValueError(f"{column} contains unparseable timestamps.")
    return parsed.where(mask, None)


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
