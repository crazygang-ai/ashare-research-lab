"""Run manifest construction and writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json


MANIFEST_SCHEMA_VERSION = "phase5.run_manifest.v1"

MANIFEST_KEYS = [
    "schema_version",
    "run_id",
    "run_mode",
    "command",
    "argv",
    "db_path",
    "as_of_date",
    "source_run_id",
    "status",
    "started_at",
    "finished_at",
    "config_hash",
    "data_snapshot_id",
    "git",
    "inputs",
    "artifacts",
    "warnings",
    "error",
    "overwrite_run",
]


def build_manifest(
    *,
    run_id: str,
    run_mode: str,
    command: str,
    argv: list[str],
    db_path: str,
    as_of_date: str | None,
    source_run_id: str | None,
    status: str,
    started_at: str,
    finished_at: str | None,
    config_hash: str | None,
    data_snapshot_id: str | None,
    git: Mapping[str, Any],
    inputs: list[Mapping[str, Any]],
    artifacts: list[Mapping[str, Any]],
    warnings: list[str],
    error: str | None,
    overwrite_run: bool,
) -> dict[str, Any]:
    values = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "run_mode": run_mode,
        "command": command,
        "argv": argv,
        "db_path": db_path,
        "as_of_date": as_of_date,
        "source_run_id": source_run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "config_hash": config_hash,
        "data_snapshot_id": data_snapshot_id,
        "git": dict(git),
        "inputs": [_manifest_input(item) for item in inputs],
        "artifacts": [_manifest_artifact(item) for item in artifacts],
        "warnings": list(warnings),
        "error": error,
        "overwrite_run": overwrite_run,
    }
    return {key: values[key] for key in MANIFEST_KEYS}


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _manifest_input(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input_id": row.get("input_id"),
        "input_kind": row.get("input_kind"),
        "input_ref": row.get("input_ref"),
        "source_run_id": row.get("source_run_id"),
        "sha256": row.get("sha256"),
        "row_count": row.get("row_count"),
        "metadata": row.get("metadata", {}),
    }


def _manifest_artifact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": row.get("artifact_id"),
        "artifact_kind": row.get("artifact_kind"),
        "role": row.get("role"),
        "path": row.get("path"),
        "media_type": row.get("media_type"),
        "sha256": row.get("sha256"),
        "row_count": row.get("row_count"),
        "size_bytes": row.get("size_bytes"),
        "metadata": row.get("metadata", {}),
    }
