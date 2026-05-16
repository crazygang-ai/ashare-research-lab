"""Read-only artifact registry for generated report directories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb

from ashare.service.config import ServiceConfig
from ashare.service.schemas import jsonable


ARTIFACT_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "scan": ("candidates.csv", "candidate_list.md"),
    "scoring": ("scoring_report.md", "scored_candidates.csv", "score_metadata.json"),
    "backtest": ("backtest_report.md", "metrics.csv", "equity_curve.csv"),
    "factor_validation": (
        "factor_validation_report.md",
        "coverage.csv",
        "rank_ic.csv",
        "ic_summary.csv",
    ),
    "event_study": (
        "event_study_report.md",
        "event_samples.csv",
        "event_window_returns.csv",
        "event_summary.csv",
    ),
}

ARTIFACT_MARKDOWN_FILES = {
    "scan": "candidate_list.md",
    "scoring": "scoring_report.md",
    "backtest": "backtest_report.md",
    "factor_validation": "factor_validation_report.md",
    "event_study": "event_study_report.md",
}

ARTIFACT_PRIMARY_CSV = {
    "scan": "candidates.csv",
    "scoring": "scored_candidates.csv",
    "backtest": "metrics.csv",
    "factor_validation": "ic_summary.csv",
    "event_study": "event_summary.csv",
}


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    title: str
    output_dir: Path
    output_dir_display: str
    files: dict[str, Path]
    file_display: dict[str, str]
    metadata: dict[str, Any]
    warnings: list[str]
    updated_at: str
    sort_timestamp: float
    run_id: str | None = None
    run_metadata: dict[str, Any] | None = None
    artifact_rows: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "run_id": self.run_id,
            "title": self.title,
            "output_dir": self.output_dir_display,
            "files": self.file_display,
            "metadata": jsonable(self.metadata),
            "run": jsonable(self.run_metadata or {}),
            "artifact_rows": jsonable(self.artifact_rows or []),
            "warnings": list(self.warnings),
            "updated_at": self.updated_at,
        }


class ArtifactRegistry:
    """Scan configured artifact roots and expose stable id based lookup."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config

    def list_artifacts(self, kind: str | None = None, limit: int | None = None) -> list[ArtifactRecord]:
        records = self._indexed_records()
        if not records:
            for root in self.config.artifact_roots:
                records.extend(self._scan_root(root))
        if kind is not None:
            records = [record for record in records if record.kind == kind]
        records = sorted(
            records,
            key=lambda record: (-record.sort_timestamp, record.kind, record.output_dir_display),
        )
        if limit is not None:
            records = records[:limit]
        return records

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        if not _looks_like_artifact_id(artifact_id):
            return None
        for record in self.list_artifacts(limit=None):
            row_ids = {
                str(row.get("artifact_id"))
                for row in (record.artifact_rows or [])
                if row.get("artifact_id")
            }
            if record.artifact_id == artifact_id or artifact_id in row_ids:
                return record
        return None

    def latest(self, kind: str) -> ArtifactRecord | None:
        records = self.list_artifacts(kind=kind, limit=1)
        return records[0] if records else None

    def read_markdown(self, artifact_id: str) -> str | None:
        record = self.get(artifact_id)
        if record is None:
            return None
        filename = ARTIFACT_MARKDOWN_FILES[record.kind]
        path = record.files.get(filename)
        if path is None:
            return None
        if not record.artifact_rows:
            self._assert_inside_configured_root(path)
        return path.read_text(encoding="utf-8")

    def read_csv(self, artifact_id: str, filename: str) -> pd.DataFrame:
        record = self.get(artifact_id)
        if record is None:
            raise FileNotFoundError(f"Unknown artifact_id: {artifact_id}")
        path = record.files.get(filename)
        if path is None:
            raise FileNotFoundError(
                f"Artifact {artifact_id} does not contain required file {filename}."
            )
        if not record.artifact_rows:
            self._assert_inside_configured_root(path)
        return pd.read_csv(path)

    def _scan_root(self, root: Path) -> list[ArtifactRecord]:
        resolved_root = root.resolve()
        if not resolved_root.exists() or not resolved_root.is_dir():
            return []
        records: list[ArtifactRecord] = []
        for dirpath, dirnames, filenames in os.walk(resolved_root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if _is_inside(Path(dirpath) / name, resolved_root)
            ]
            directory = Path(dirpath).resolve()
            present = set(filenames)
            for kind in self.config.known_artifact_kinds:
                if kind not in ARTIFACT_REQUIRED_FILES:
                    continue
                required = set(ARTIFACT_REQUIRED_FILES[kind])
                if not required.intersection(present):
                    continue
                records.append(self._build_record(kind, directory, resolved_root, present))
        return records

    def audit_schema_available(self) -> bool:
        return _audit_tables_available(self.config.database_path)

    def artifact_index_available(self) -> bool:
        return bool(self._indexed_records(limit=1))

    def latest_run_id(self, *, formal: bool = False) -> str | None:
        if not self.audit_schema_available():
            return None
        connection = duckdb.connect(str(self.config.database_path), read_only=True)
        try:
            if formal:
                row = connection.execute(
                    """
                    SELECT run_id
                    FROM research_runs
                    WHERE json_extract_string(params, '$.run_mode') = 'formal'
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id
                    LIMIT 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT run_id
                    FROM research_runs
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id
                    LIMIT 1
                    """
                ).fetchone()
        finally:
            connection.close()
        return str(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.audit_schema_available():
            return []
        connection = duckdb.connect(str(self.config.database_path), read_only=True)
        try:
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
        finally:
            connection.close()
        return [_run_row_to_dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self.audit_schema_available():
            return None
        connection = duckdb.connect(str(self.config.database_path), read_only=True)
        try:
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
        finally:
            connection.close()
        return _run_row_to_dict(row) if row else None

    def artifacts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        if not self.audit_schema_available():
            return []
        connection = duckdb.connect(str(self.config.database_path), read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT artifact_id, run_id, artifact_kind, role, path, media_type, sha256,
                       row_count, size_bytes, CAST(created_at AS VARCHAR), metadata_json
                FROM research_artifacts
                WHERE run_id = ?
                ORDER BY artifact_kind, role, path
                """,
                [run_id],
            ).fetchall()
        finally:
            connection.close()
        return [_artifact_row_to_dict(row) for row in rows]

    def manifest_for_run(self, run_id: str) -> str | None:
        manifest_rows = [
            row for row in self.artifacts_for_run(run_id) if row.get("role") == "manifest"
        ]
        if not manifest_rows:
            return None
        path = self._resolve_artifact_path(str(manifest_rows[0]["path"]))
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def _indexed_records(self, limit: int | None = None) -> list[ArtifactRecord]:
        if not self.audit_schema_available():
            return []
        connection = duckdb.connect(str(self.config.database_path), read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT
                    a.artifact_id, a.run_id, a.artifact_kind, a.role, a.path,
                    a.media_type, a.sha256, a.row_count, a.size_bytes,
                    CAST(a.created_at AS VARCHAR), a.metadata_json,
                    r.status, r.params, r.git_sha, r.worktree_clean,
                    CAST(r.started_at AS VARCHAR), CAST(r.finished_at AS VARCHAR),
                    r.config_hash, r.data_snapshot_id, r.error
                FROM research_artifacts a
                LEFT JOIN research_runs r ON r.run_id = a.run_id
                ORDER BY a.created_at DESC, a.run_id, a.role
                """
            ).fetchall()
        except duckdb.Error:
            return []
        finally:
            connection.close()
        records = _group_index_rows(rows, self.config)
        if limit is not None:
            return records[:limit]
        return records

    def _build_record(
        self,
        kind: str,
        directory: Path,
        root: Path,
        present: set[str],
    ) -> ArtifactRecord:
        required = set(ARTIFACT_REQUIRED_FILES[kind])
        warnings = [
            f"Missing required file for {kind} artifact: {filename}"
            for filename in sorted(required.difference(present))
        ]
        files: dict[str, Path] = {}
        file_display: dict[str, str] = {}
        known_files = required.union({"score_metadata.json"})
        for filename in sorted(known_files.intersection(present)):
            path = (directory / filename).resolve()
            if _is_inside(path, root):
                files[filename] = path
                file_display[filename] = self.config.repo_relative(path)
        metadata = _load_metadata(files)
        sort_timestamp, updated_at = _metadata_sort_time(metadata, directory, files)
        output_dir_display = self.config.repo_relative(directory)
        artifact_id = _artifact_id(kind, output_dir_display)
        title = _artifact_title(kind, output_dir_display, metadata)
        return ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            title=title,
            output_dir=directory,
            output_dir_display=output_dir_display,
            files=files,
            file_display=file_display,
            metadata=metadata,
            warnings=warnings,
            updated_at=updated_at,
            sort_timestamp=sort_timestamp,
        )

    def _assert_inside_configured_root(self, path: Path) -> None:
        resolved = path.resolve()
        for root in self.config.artifact_roots:
            if _is_inside(resolved, root.resolve()):
                return
        raise ValueError(f"Refusing to read file outside configured artifact roots: {path}")

    def _assert_inside_configured_root_or_repo(self, path: Path) -> None:
        resolved = path.resolve()
        if _is_inside(resolved, self.config.repo_root):
            return
        self._assert_inside_configured_root(path)

    def _resolve_artifact_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path.resolve()
        return self.config.resolve_path(path)


def _artifact_id(kind: str, output_dir_display: str) -> str:
    source = f"{kind}|{output_dir_display}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


def _looks_like_artifact_id(value: str) -> bool:
    return len(value) in {12, 40} and all(char in "0123456789abcdef" for char in value)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_metadata(files: dict[str, Path]) -> dict[str, Any]:
    metadata_path = files.get("score_metadata.json")
    if metadata_path is None:
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"metadata_error": str(exc)}
    return data if isinstance(data, dict) else {"metadata_value": data}


def _metadata_sort_time(
    metadata: dict[str, Any],
    directory: Path,
    files: dict[str, Path],
) -> tuple[float, str]:
    generated_at = metadata.get("generated_at")
    if isinstance(generated_at, str):
        parsed = _parse_datetime(generated_at)
        if parsed is not None:
            return parsed.timestamp(), generated_at
    mtimes = [path.stat().st_mtime for path in files.values() if path.exists()]
    if not mtimes and directory.exists():
        mtimes = [directory.stat().st_mtime]
    timestamp = max(mtimes) if mtimes else 0.0
    updated_at = datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")
    return timestamp, updated_at


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _artifact_title(kind: str, output_dir_display: str, metadata: dict[str, Any]) -> str:
    if isinstance(metadata.get("title"), str):
        return str(metadata["title"])
    for key in ["as_of_date", "validation_to", "end_date", "generated_at"]:
        value = metadata.get(key)
        if value:
            return f"{kind} {value}"
    return f"{kind} {Path(output_dir_display).name}"


def _audit_tables_available(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        connection = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error:
        return False
    try:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
    except duckdb.Error:
        return False
    finally:
        connection.close()
    return {"research_runs", "research_artifacts", "research_run_inputs"}.issubset(tables)


def _group_index_rows(rows: list[tuple[Any, ...]], config: ServiceConfig) -> list[ArtifactRecord]:
    groups: dict[tuple[str, str, str], list[tuple[Any, ...]]] = {}
    for row in rows:
        path = str(row[4])
        output_dir = str(Path(path).parent)
        groups.setdefault((str(row[1]), str(row[2]), output_dir), []).append(row)

    records: list[ArtifactRecord] = []
    for (run_id, kind, output_dir_display), group_rows in groups.items():
        artifact_rows = [_artifact_row_to_dict(row[:11]) for row in group_rows]
        files: dict[str, Path] = {}
        file_display: dict[str, str] = {}
        warnings: list[str] = []
        for artifact in artifact_rows:
            path_value = str(artifact["path"])
            path = Path(path_value)
            resolved = path.resolve() if path.is_absolute() else config.resolve_path(path)
            filename = resolved.name
            files[filename] = resolved
            file_display[filename] = path_value
            if not resolved.exists():
                warnings.append(f"Indexed artifact file is missing: {path_value}")

        first = group_rows[0]
        params = _json_value(first[12])
        run_metadata = {
            "run_id": run_id,
            "status": first[11],
            "params": params,
            "git_sha": first[13],
            "worktree_clean": first[14],
            "started_at": first[15],
            "finished_at": first[16],
            "config_hash": first[17],
            "data_snapshot_id": first[18],
            "error": first[19],
        }
        metadata = {
            "run_id": run_id,
            "run_mode": params.get("run_mode") if isinstance(params, dict) else None,
            "source_run_id": params.get("source_run_id") if isinstance(params, dict) else None,
            "status": first[11],
        }
        updated_at = str(first[16] or first[9] or first[15] or "")
        sort_timestamp = _sort_timestamp(updated_at)
        group_id = _artifact_id(kind, f"{run_id}|{output_dir_display}")
        records.append(
            ArtifactRecord(
                artifact_id=group_id,
                kind=kind,
                title=_artifact_title(kind, output_dir_display, metadata),
                output_dir=config.resolve_path(output_dir_display),
                output_dir_display=output_dir_display,
                files=files,
                file_display=file_display,
                metadata=metadata,
                warnings=warnings,
                updated_at=updated_at,
                sort_timestamp=sort_timestamp,
                run_id=run_id,
                run_metadata=run_metadata,
                artifact_rows=artifact_rows,
            )
        )
    return sorted(
        records,
        key=lambda record: (-record.sort_timestamp, record.kind, record.output_dir_display),
    )


def _artifact_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "artifact_id": row[0],
        "run_id": row[1],
        "artifact_kind": row[2],
        "role": row[3],
        "path": row[4],
        "media_type": row[5],
        "sha256": row[6],
        "row_count": row[7],
        "size_bytes": row[8],
        "created_at": row[9],
        "metadata": _json_value(row[10]),
    }


def _run_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "run_id": row[0],
        "as_of_date": row[1],
        "status": row[2],
        "params": _json_value(row[3]),
        "config_hash": row[4],
        "data_snapshot_id": row[5],
        "git_sha": row[6],
        "worktree_clean": row[7],
        "started_at": row[8],
        "finished_at": row[9],
        "error": row[10],
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value if value is not None else {}


def _sort_timestamp(value: str) -> float:
    parsed = _parse_datetime(value) if value else None
    return parsed.timestamp() if parsed is not None else 0.0
