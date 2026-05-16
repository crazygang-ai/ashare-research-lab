"""Input fingerprint builders for Phase 5 audit."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

import duckdb

from ashare.audit.hashing import file_size, sha256_file, sha256_json


def input_id(run_id: str, input_kind: str, input_ref: str, source_run_id: str | None = None) -> str:
    source = source_run_id or ""
    return hashlib.sha1(f"{run_id}|{input_kind}|{input_ref}|{source}".encode("utf-8")).hexdigest()


def config_file_input(
    *,
    repo_root: Path,
    run_id: str,
    path: Path,
    created_at: datetime,
) -> dict[str, Any]:
    display = _display_path(repo_root, path)
    resolved = path.resolve()
    return {
        "input_id": input_id(run_id, "config_file", display),
        "run_id": run_id,
        "input_kind": "config_file",
        "input_ref": display,
        "source_run_id": None,
        "sha256": sha256_file(resolved) if resolved.exists() and resolved.is_file() else None,
        "row_count": None,
        "metadata": {"size_bytes": file_size(resolved) if resolved.exists() else None},
        "created_at": created_at,
    }


def artifact_file_input(
    *,
    repo_root: Path,
    run_id: str,
    path: Path,
    created_at: datetime,
) -> dict[str, Any]:
    display = _display_path(repo_root, path)
    resolved = path.resolve()
    return {
        "input_id": input_id(run_id, "artifact_file", display),
        "run_id": run_id,
        "input_kind": "artifact_file",
        "input_ref": display,
        "source_run_id": None,
        "sha256": sha256_file(resolved) if resolved.exists() and resolved.is_file() else None,
        "row_count": None,
        "metadata": {"size_bytes": file_size(resolved) if resolved.exists() else None},
        "created_at": created_at,
    }


def cli_param_input(
    *,
    run_id: str,
    name: str,
    value: str,
    created_at: datetime,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    ref = f"{name}:{value}"
    return {
        "input_id": input_id(run_id, "cli_param", ref, source_run_id),
        "run_id": run_id,
        "input_kind": "cli_param",
        "input_ref": ref,
        "source_run_id": source_run_id,
        "sha256": None,
        "row_count": None,
        "metadata": {"name": name, "value": value},
        "created_at": created_at,
    }


def git_state_input(
    *,
    run_id: str,
    sha: str | None,
    worktree_clean: bool | None,
    dirty_files: list[str],
    warnings: list[str],
    created_at: datetime,
) -> dict[str, Any]:
    metadata = {
        "sha": sha,
        "worktree_clean": worktree_clean,
        "dirty_files": dirty_files,
        "warnings": warnings,
    }
    return {
        "input_id": input_id(run_id, "git_state", "git"),
        "run_id": run_id,
        "input_kind": "git_state",
        "input_ref": "git",
        "source_run_id": None,
        "sha256": sha256_json(metadata),
        "row_count": None,
        "metadata": metadata,
        "created_at": created_at,
    }


def duckdb_table_input(
    *,
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    table_name: str,
    created_at: datetime,
    source_run_id: str | None = None,
    predicate: str | None = None,
) -> dict[str, Any]:
    metadata = table_metadata_fingerprint(
        connection,
        table_name=table_name,
        source_run_id=source_run_id,
        predicate=predicate,
    )
    return {
        "input_id": input_id(run_id, "duckdb_table", table_name, source_run_id),
        "run_id": run_id,
        "input_kind": "duckdb_table",
        "input_ref": table_name,
        "source_run_id": source_run_id,
        "sha256": sha256_json(metadata),
        "row_count": metadata.get("row_count"),
        "metadata": metadata,
        "created_at": created_at,
    }


def table_metadata_fingerprint(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    source_run_id: str | None = None,
    predicate: str | None = None,
) -> dict[str, Any]:
    columns = _table_columns(connection, table_name)
    if not columns:
        return {"table": table_name, "exists": False, "predicate": predicate}
    where = ""
    params: list[Any] = []
    if source_run_id is not None and "source_run_id" in columns:
        where = "WHERE source_run_id = ?"
        params.append(source_run_id)
    row_count = int(
        connection.execute(f"SELECT COUNT(*) FROM {table_name} {where}", params).fetchone()[0]
    )
    metadata: dict[str, Any] = {
        "table": table_name,
        "exists": True,
        "row_count": row_count,
        "source_run_id": source_run_id,
        "predicate": predicate,
    }
    for date_col in ["trade_date", "as_of_date", "effective_date", "publish_time", "created_at"]:
        if date_col in columns:
            row = connection.execute(
                f"SELECT CAST(MIN({date_col}) AS VARCHAR), CAST(MAX({date_col}) AS VARCHAR) FROM {table_name} {where}",
                params,
            ).fetchone()
            metadata[f"{date_col}_min"] = row[0]
            metadata[f"{date_col}_max"] = row[1]
    for source_col in ["source", "source_tag"]:
        if source_col in columns:
            values = [
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT {source_col} FROM {table_name} {where} ORDER BY {source_col} LIMIT 20",
                    params,
                ).fetchall()
            ]
            metadata[f"{source_col}_values"] = values
    return metadata


def data_snapshot_id(inputs: list[Mapping[str, Any]]) -> str:
    material = [
        {
            "input_kind": item.get("input_kind"),
            "input_ref": item.get("input_ref"),
            "source_run_id": item.get("source_run_id"),
            "sha256": item.get("sha256"),
            "row_count": item.get("row_count"),
            "metadata": item.get("metadata", {}),
        }
        for item in inputs
        if item.get("input_kind") in {"duckdb_table", "duckdb_query", "artifact_file", "config_file", "cli_param"}
    ]
    return f"fingerprint:{sha256_json(material)}"


def _table_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchall()
    return {str(row[0]) for row in rows}


def _display_path(repo_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()
