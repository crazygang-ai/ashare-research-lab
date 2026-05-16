"""Read-only service query helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ashare.service.artifacts import ArtifactRecord, ArtifactRegistry
from ashare.service.config import ServiceConfig
from ashare.service.schemas import dataframe_rows


CSV_REQUIRED_COLUMNS = {
    "candidates.csv": {"stock_code"},
    "scored_candidates.csv": {"stock_code"},
    "coverage.csv": {"factor_name"},
    "rank_ic.csv": {"factor_name"},
    "ic_summary.csv": {"factor_name"},
    "daily_candidates.csv": {"stock_code"},
    "stock_factor_values.csv": {"stock_code", "factor_name"},
    "data_quality_gate.csv": {"check_name", "status", "severity"},
}


def database_available(config: ServiceConfig) -> bool:
    db_path = config.database_path
    if not db_path.exists():
        return False
    try:
        connection = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error:
        return False
    connection.close()
    return True


def read_artifact_csv(
    registry: ArtifactRegistry,
    artifact: ArtifactRecord,
    filename: str,
) -> pd.DataFrame:
    frame = registry.read_csv(artifact.artifact_id, filename)
    required = CSV_REQUIRED_COLUMNS.get(filename, set())
    missing = sorted(required.difference(str(column) for column in frame.columns))
    if missing:
        raise ValueError(f"{filename} is missing required column(s): {', '.join(missing)}")
    return frame


def artifact_csv_payload(
    registry: ArtifactRegistry,
    artifact: ArtifactRecord,
    filename: str,
    *,
    payload_key: str = "rows",
) -> dict[str, Any]:
    frame = read_artifact_csv(registry, artifact, filename)
    return {
        "artifact_id": artifact.artifact_id,
        "artifact": artifact.to_dict(),
        "columns": [str(column) for column in frame.columns],
        payload_key: dataframe_rows(frame),
    }


def factor_validation_payload(
    registry: ArtifactRegistry,
    artifact: ArtifactRecord,
    factor_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "artifact_id": artifact.artifact_id,
        "artifact": artifact.to_dict(),
        "factor_name": factor_name,
    }
    for filename, key in [
        ("coverage.csv", "coverage"),
        ("rank_ic.csv", "rank_ic"),
        ("ic_summary.csv", "ic_summary"),
    ]:
        frame = read_artifact_csv(registry, artifact, filename)
        result[key] = dataframe_rows(frame[frame["factor_name"].astype(str) == factor_name])
    return result


def query_stock_factors(
    config: ServiceConfig,
    stock_code: str,
    as_of: str,
    source_run_id: str,
) -> list[dict[str, Any]]:
    db_path = config.database_path
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB file does not exist: {config.repo_relative(db_path)}")
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        frame = connection.execute(
            """
            SELECT
                stock_code,
                trade_date,
                factor_name,
                factor_value,
                as_of_date,
                source_run_id
            FROM factor_values
            WHERE stock_code = ?
              AND as_of_date = CAST(? AS DATE)
              AND source_run_id = ?
            ORDER BY trade_date, factor_name
            """,
            [stock_code, as_of, source_run_id],
        ).fetchdf()
    finally:
        connection.close()
    return dataframe_rows(frame)


def count_factor_values(db_path: Path) -> int:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0])
    finally:
        connection.close()
