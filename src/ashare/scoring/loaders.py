"""Data loaders for Phase 3 composite scoring."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import duckdb
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date, query_universe_members_as_of
from ashare.storage.universe_snapshots import load_factor_run_universe


SCORE_INPUT_COLUMNS = [
    "stock_code",
    "trade_date",
    "factor_name",
    "factor_value",
    "as_of_date",
    "source_run_id",
]


def load_score_inputs(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    index_code: str,
    factor_names: Sequence[str],
    hard_filter_names: Sequence[str],
    data_source: str | None = None,
) -> pd.DataFrame:
    """Load one-day PIT factor rows for the requested score universe."""
    score_date = parse_as_of_date(as_of_date)
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    if not index_code or not str(index_code).strip():
        raise ValueError("index_code must be explicitly provided.")

    snapshot = load_factor_run_universe(
        connection,
        source_run_id=source_run_id,
        trade_date=score_date,
        index_code=str(index_code),
    )
    universe_source = "factor_run_universe"
    if snapshot.empty:
        universe = query_universe_members_as_of(
            connection,
            score_date,
            index_code=str(index_code),
            source_tag=None if data_source == "legacy" else data_source,
        )
        universe_source = "pit_universe_members_fallback"
    else:
        universe = snapshot
    if universe.empty:
        result = pd.DataFrame(columns=SCORE_INPUT_COLUMNS)
        result.attrs["universe"] = pd.DataFrame(columns=["index_code", "stock_code"])
        result.attrs["score_date"] = score_date
        result.attrs["index_code"] = index_code
        result.attrs["universe_source"] = universe_source
        return result

    universe = universe.loc[:, ["index_code", "stock_code"]].drop_duplicates(
        "stock_code",
        keep="first",
    )
    names = tuple(dict.fromkeys([*map(str, factor_names), *map(str, hard_filter_names)]))
    if not names:
        frame = pd.DataFrame(columns=SCORE_INPUT_COLUMNS)
    else:
        placeholders = ", ".join("?" for _ in names)
        params: list[Any] = [source_run_id, score_date, score_date, *names]
        frame = connection.execute(
            f"""
            SELECT stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            FROM factor_values
            WHERE source_run_id = ?
              AND trade_date = ?
              AND as_of_date = ?
              AND as_of_date = trade_date
              AND factor_name IN ({placeholders})
            ORDER BY stock_code, factor_name
            """,
            params,
        ).df()
    normalized = _normalize_factor_values(frame)
    normalized = normalized[normalized["stock_code"].isin(set(universe["stock_code"]))].copy()
    _fail_on_duplicate_factor_keys(normalized)
    normalized = normalized.sort_values(["stock_code", "factor_name"], kind="mergesort").reset_index(
        drop=True
    )
    normalized.attrs["universe"] = universe.sort_values("stock_code", kind="mergesort").reset_index(
        drop=True
    )
    normalized.attrs["score_date"] = score_date
    normalized.attrs["index_code"] = index_code
    normalized.attrs["universe_source"] = universe_source
    if "fingerprint" in universe.columns and not universe.empty:
        normalized.attrs["universe_fingerprint"] = str(universe["fingerprint"].iloc[0])
    return normalized


def fail_on_duplicate_factor_keys(factor_values: pd.DataFrame) -> None:
    """Public duplicate-key guard shared by tests and scoring internals."""
    _fail_on_duplicate_factor_keys(factor_values)


def _normalize_factor_values(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=SCORE_INPUT_COLUMNS)
    result = frame.loc[:, SCORE_INPUT_COLUMNS].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    result["as_of_date"] = pd.to_datetime(result["as_of_date"]).dt.date
    result["factor_value"] = pd.to_numeric(result["factor_value"], errors="coerce")
    return result


def _fail_on_duplicate_factor_keys(factor_values: pd.DataFrame) -> None:
    if factor_values.empty:
        return
    duplicate_counts = (
        factor_values.groupby(
            ["source_run_id", "stock_code", "trade_date", "as_of_date", "factor_name"],
            dropna=False,
        )
        .size()
        .reset_index(name="row_count")
    )
    duplicates = duplicate_counts[duplicate_counts["row_count"] >= 2]
    if duplicates.empty:
        return
    samples = []
    for row in duplicates.head(5).itertuples(index=False):
        samples.append(
            f"({row.source_run_id}, {row.stock_code}, {row.trade_date}, "
            f"{row.as_of_date}, {row.factor_name}, count={row.row_count})"
        )
    raise ValueError(
        "Duplicate factor_values rows for "
        "(source_run_id, stock_code, trade_date, as_of_date, factor_name). "
        f"Examples: {'; '.join(samples)}"
    )


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()
