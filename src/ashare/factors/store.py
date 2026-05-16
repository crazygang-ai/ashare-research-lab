"""DuckDB storage for calculated factor values with duplicate-key governance."""

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
FACTOR_VALUE_KEY_COLUMNS = [
    "source_run_id",
    "stock_code",
    "trade_date",
    "as_of_date",
    "factor_name",
]


def write_factor_values(
    connection: duckdb.DuckDBPyConnection,
    factors: pd.DataFrame,
    source_run_id: str,
    replace: bool = False,
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

    _raise_on_incoming_duplicates(clean)

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
        else:
            _raise_on_existing_duplicates(connection, clean, source_run_id)

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


def delete_factor_values_for_source_run(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
) -> int:
    """Delete all factor rows for a source run and return deleted row count."""
    count = int(
        connection.execute(
            "SELECT COUNT(*) FROM factor_values WHERE source_run_id = ?",
            [source_run_id],
        ).fetchone()[0]
    )
    connection.execute("DELETE FROM factor_values WHERE source_run_id = ?", [source_run_id])
    return count


def _raise_on_incoming_duplicates(clean: pd.DataFrame) -> None:
    duplicated = clean[clean.duplicated(FACTOR_VALUE_KEY_COLUMNS, keep=False)]
    if duplicated.empty:
        return
    raise ValueError(
        "Duplicate incoming factor_values keys: " + _duplicate_sample(duplicated)
    )


def _raise_on_existing_duplicates(
    connection: duckdb.DuckDBPyConnection,
    clean: pd.DataFrame,
    source_run_id: str,
) -> None:
    keys = clean.loc[:, ["stock_code", "trade_date", "as_of_date", "factor_name"]].drop_duplicates()
    if keys.empty:
        return
    connection.register("_incoming_factor_keys", keys)
    try:
        duplicates = connection.execute(
            """
            SELECT
                fv.source_run_id,
                fv.stock_code,
                fv.trade_date,
                fv.as_of_date,
                fv.factor_name
            FROM factor_values fv
            INNER JOIN _incoming_factor_keys incoming
              ON fv.stock_code = incoming.stock_code
             AND fv.trade_date = incoming.trade_date
             AND fv.as_of_date = incoming.as_of_date
             AND fv.factor_name = incoming.factor_name
            WHERE fv.source_run_id = ?
            ORDER BY fv.stock_code, fv.trade_date, fv.as_of_date, fv.factor_name
            LIMIT 5
            """,
            [source_run_id],
        ).fetchdf()
    finally:
        connection.unregister("_incoming_factor_keys")
    if duplicates.empty:
        return
    raise ValueError(
        "factor_values already contains rows for source_run_id; use --overwrite-run "
        "to replace an audited factor run. Duplicate key sample: "
        + _duplicate_sample(duplicates)
    )


def _duplicate_sample(frame: pd.DataFrame) -> str:
    rows = []
    for row in frame.loc[:, FACTOR_VALUE_KEY_COLUMNS].head(5).itertuples(index=False):
        rows.append(
            f"({row.source_run_id}, {row.stock_code}, {row.trade_date}, "
            f"{row.as_of_date}, {row.factor_name})"
        )
    return "; ".join(rows)
