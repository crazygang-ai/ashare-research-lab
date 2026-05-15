"""Idempotent DuckDB storage for calculated factor values."""

from __future__ import annotations

import math

import duckdb
import pandas as pd


REQUIRED_COLUMNS = {"stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"}
INSERT_COLUMNS = [
    "stock_code",
    "trade_date",
    "factor_name",
    "factor_value",
    "as_of_date",
    "source_run_id",
]


def write_factor_values(
    connection: duckdb.DuckDBPyConnection,
    factors: pd.DataFrame,
    source_run_id: str,
    replace: bool = True,
) -> int:
    """Write factor rows to ``factor_values`` and return the inserted row count."""
    missing = REQUIRED_COLUMNS - set(factors.columns)
    if missing:
        raise ValueError(f"Factor DataFrame is missing required columns: {sorted(missing)}")

    clean = factors.loc[:, sorted(REQUIRED_COLUMNS)].copy()
    clean = clean[pd.notna(clean["factor_value"])]
    if clean.empty:
        return 0

    clean["trade_date"] = pd.to_datetime(clean["trade_date"]).dt.date
    clean["as_of_date"] = pd.to_datetime(clean["as_of_date"]).dt.date
    clean["factor_value"] = clean["factor_value"].astype(float)
    clean = clean[clean["factor_value"].map(math.isfinite)]
    clean["source_run_id"] = source_run_id
    clean = clean.loc[:, INSERT_COLUMNS]
    if clean.empty:
        return 0

    try:
        connection.execute("BEGIN TRANSACTION")
        if replace:
            keys = clean[["as_of_date", "trade_date", "factor_name"]].drop_duplicates()
            connection.executemany(
                """
                DELETE FROM factor_values
                WHERE source_run_id = ?
                  AND as_of_date = ?
                  AND trade_date = ?
                  AND factor_name = ?
                """,
                [
                    (source_run_id, row.as_of_date, row.trade_date, row.factor_name)
                    for row in keys.itertuples(index=False)
                ],
            )

        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code,
                trade_date,
                factor_name,
                factor_value,
                as_of_date,
                source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [tuple(row) for row in clean.itertuples(index=False, name=None)],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return len(clean)
