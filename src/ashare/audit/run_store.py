"""DuckDB persistence for Phase 5 run audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Mapping

import duckdb

from ashare.audit.hashing import stable_json


RUN_STATUSES = {"running", "succeeded", "failed", "aborted"}


class DuplicateRunError(ValueError):
    """Raised when a run_id already exists and overwrite is not allowed."""


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    as_of_date: str | None
    status: str
    params: dict[str, Any]
    config_hash: str | None
    data_snapshot_id: str | None
    git_sha: str | None
    worktree_clean: bool | None
    started_at: str | None
    finished_at: str | None
    error: str | None


def ensure_audit_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id VARCHAR,
            as_of_date DATE,
            status VARCHAR,
            params JSON,
            config_hash VARCHAR,
            data_snapshot_id VARCHAR,
            git_sha VARCHAR,
            worktree_clean BOOLEAN,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            error VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_artifacts (
            artifact_id VARCHAR,
            run_id VARCHAR,
            artifact_kind VARCHAR,
            role VARCHAR,
            path VARCHAR,
            media_type VARCHAR,
            sha256 VARCHAR,
            row_count BIGINT,
            size_bytes BIGINT,
            created_at TIMESTAMP,
            metadata_json JSON
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_run_inputs (
            input_id VARCHAR,
            run_id VARCHAR,
            input_kind VARCHAR,
            input_ref VARCHAR,
            source_run_id VARCHAR,
            sha256 VARCHAR,
            row_count BIGINT,
            metadata_json JSON,
            created_at TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER,
            applied_at TIMESTAMP,
            description VARCHAR
        )
        """
    )


def begin_run(
    connection: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    as_of_date: str | None,
    params: Mapping[str, Any],
    config_hash: str | None,
    data_snapshot_id: str | None,
    git_sha: str | None,
    worktree_clean: bool | None,
    started_at: datetime,
    overwrite: bool,
) -> None:
    ensure_audit_schema(connection)
    if run_exists(connection, run_id):
        if not overwrite:
            raise DuplicateRunError(f"run_id already exists: {run_id}")
        delete_run(connection, run_id)
    connection.execute(
        """
        INSERT INTO research_runs (
            run_id, as_of_date, status, params, config_hash, data_snapshot_id,
            git_sha, worktree_clean, started_at, finished_at, error
        )
        VALUES (?, TRY_CAST(? AS DATE), 'running', ?::JSON, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        [
            run_id,
            as_of_date,
            stable_json(params),
            config_hash,
            data_snapshot_id,
            git_sha,
            worktree_clean,
            started_at,
        ],
    )


def complete_run(
    connection: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    status: str,
    params: Mapping[str, Any],
    config_hash: str | None,
    data_snapshot_id: str | None,
    finished_at: datetime,
    error: str | None,
) -> None:
    if status not in RUN_STATUSES:
        raise ValueError(f"Unsupported run status: {status}")
    connection.execute(
        """
        UPDATE research_runs
        SET status = ?,
            params = ?::JSON,
            config_hash = ?,
            data_snapshot_id = ?,
            finished_at = ?,
            error = ?
        WHERE run_id = ?
        """,
        [
            status,
            stable_json(params),
            config_hash,
            data_snapshot_id,
            finished_at,
            _compact_error(error),
            run_id,
        ],
    )


def insert_inputs(connection: duckdb.DuckDBPyConnection, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        return
    connection.executemany(
        """
        INSERT INTO research_run_inputs (
            input_id, run_id, input_kind, input_ref, source_run_id, sha256,
            row_count, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, ?)
        """,
        [
            (
                row["input_id"],
                row["run_id"],
                row["input_kind"],
                row["input_ref"],
                row.get("source_run_id"),
                row.get("sha256"),
                row.get("row_count"),
                stable_json(row.get("metadata", {})),
                row["created_at"],
            )
            for row in rows
        ],
    )


def insert_artifacts(connection: duckdb.DuckDBPyConnection, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        return
    connection.executemany(
        """
        INSERT INTO research_artifacts (
            artifact_id, run_id, artifact_kind, role, path, media_type, sha256,
            row_count, size_bytes, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)
        """,
        [
            (
                row["artifact_id"],
                row["run_id"],
                row["artifact_kind"],
                row["role"],
                row["path"],
                row["media_type"],
                row.get("sha256"),
                row.get("row_count"),
                row.get("size_bytes"),
                row["created_at"],
                stable_json(row.get("metadata", {})),
            )
            for row in rows
        ],
    )


def run_exists(connection: duckdb.DuckDBPyConnection, run_id: str) -> bool:
    ensure_audit_schema(connection)
    return bool(
        connection.execute(
            "SELECT EXISTS(SELECT 1 FROM research_runs WHERE run_id = ?)",
            [run_id],
        ).fetchone()[0]
    )


def delete_run(connection: duckdb.DuckDBPyConnection, run_id: str) -> None:
    ensure_audit_schema(connection)
    connection.execute("DELETE FROM research_artifacts WHERE run_id = ?", [run_id])
    connection.execute("DELETE FROM research_run_inputs WHERE run_id = ?", [run_id])
    connection.execute("DELETE FROM research_runs WHERE run_id = ?", [run_id])


def get_run(connection: duckdb.DuckDBPyConnection, run_id: str) -> StoredRun | None:
    ensure_audit_schema(connection)
    row = connection.execute(
        """
        SELECT run_id, CAST(as_of_date AS VARCHAR), status, params, config_hash,
               data_snapshot_id, git_sha, worktree_clean,
               CAST(started_at AS VARCHAR), CAST(finished_at AS VARCHAR), error
        FROM research_runs
        WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()
    if row is None:
        return None
    return _stored_run_from_row(row)


def list_runs(
    connection: duckdb.DuckDBPyConnection,
    *,
    limit: int = 50,
) -> list[StoredRun]:
    ensure_audit_schema(connection)
    rows = connection.execute(
        """
        SELECT run_id, CAST(as_of_date AS VARCHAR), status, params, config_hash,
               data_snapshot_id, git_sha, worktree_clean,
               CAST(started_at AS VARCHAR), CAST(finished_at AS VARCHAR), error
        FROM research_runs
        ORDER BY COALESCE(finished_at, started_at) DESC, run_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [_stored_run_from_row(row) for row in rows]


def _stored_run_from_row(row: tuple[Any, ...]) -> StoredRun:
    params = row[3]
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {"raw": params}
    elif params is None:
        params = {}
    return StoredRun(
        run_id=str(row[0]),
        as_of_date=row[1],
        status=str(row[2]),
        params=params if isinstance(params, dict) else {"value": params},
        config_hash=row[4],
        data_snapshot_id=row[5],
        git_sha=row[6],
        worktree_clean=row[7],
        started_at=row[8],
        finished_at=row[9],
        error=row[10],
    )


def _compact_error(error: str | None) -> str | None:
    if error is None:
        return None
    text = " ".join(str(error).split())
    return text[:1000]
