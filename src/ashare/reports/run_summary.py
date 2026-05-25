"""Shared helpers for Phase 7 report artifact loading and rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


@dataclass(frozen=True)
class ArtifactBundle:
    """Files indexed for one upstream audited run."""

    kind: str
    requested_run_id: str | None
    run_id: str | None
    files: dict[str, Path]
    file_display: dict[str, str]
    artifact_rows: list[dict[str, Any]]
    run_metadata: dict[str, Any]
    resolved_via: str
    warnings: tuple[str, ...] = ()

    @property
    def missing(self) -> bool:
        return self.run_id is None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requested_run_id": self.requested_run_id,
            "run_id": self.run_id,
            "resolved_via": self.resolved_via,
            "files": dict(self.file_display),
            "artifact_rows": jsonable(self.artifact_rows),
            "run": jsonable(self.run_metadata),
            "warnings": list(self.warnings),
        }


def load_artifact_bundle(
    connection: duckdb.DuckDBPyConnection,
    *,
    kind: str,
    run_id: str | None,
    repo_root: Path,
    allow_latest: bool = False,
    required_files: Sequence[str] = (),
) -> ArtifactBundle:
    """Resolve artifact files for an explicit run id, optionally falling back to latest."""
    resolved_run_id = run_id
    resolved_via = "explicit_run_id" if run_id else "missing"
    if resolved_run_id is None and allow_latest:
        resolved_run_id = _latest_run_id_for_kind(connection, kind)
        resolved_via = "latest_artifact" if resolved_run_id else "latest_not_found"

    if resolved_run_id is None:
        return ArtifactBundle(
            kind=kind,
            requested_run_id=run_id,
            run_id=None,
            files={},
            file_display={},
            artifact_rows=[],
            run_metadata={},
            resolved_via=resolved_via,
            warnings=(f"No {kind} artifact run id was provided.",),
        )

    rows = connection.execute(
        """
        SELECT
            a.artifact_id,
            a.run_id,
            a.artifact_kind,
            a.role,
            a.path,
            a.media_type,
            a.sha256,
            a.row_count,
            a.size_bytes,
            CAST(a.created_at AS VARCHAR),
            a.metadata_json,
            r.status,
            CAST(r.as_of_date AS VARCHAR),
            r.params,
            r.config_hash,
            r.data_snapshot_id,
            r.git_sha,
            r.worktree_clean,
            CAST(r.started_at AS VARCHAR),
            CAST(r.finished_at AS VARCHAR),
            r.error
        FROM research_artifacts a
        LEFT JOIN research_runs r ON r.run_id = a.run_id
        WHERE a.run_id = ?
          AND a.artifact_kind = ?
        ORDER BY a.role, a.path
        """,
        [resolved_run_id, kind],
    ).fetchall()
    if not rows:
        return ArtifactBundle(
            kind=kind,
            requested_run_id=run_id,
            run_id=resolved_run_id,
            files={},
            file_display={},
            artifact_rows=[],
            run_metadata={},
            resolved_via=resolved_via,
            warnings=(f"No indexed {kind} artifacts found for run_id={resolved_run_id}.",),
        )

    artifact_rows = [_artifact_row_to_dict(row[:11]) for row in rows]
    files: dict[str, Path] = {}
    display: dict[str, str] = {}
    warnings: list[str] = []
    for artifact in artifact_rows:
        path_value = str(artifact["path"])
        resolved = _resolve_path(repo_root, path_value)
        files[resolved.name] = resolved
        display[resolved.name] = path_value
        if not resolved.exists() or not resolved.is_file():
            warnings.append(f"Indexed artifact file is missing: {path_value}")

    missing_required = [name for name in required_files if name not in files]
    for name in missing_required:
        warnings.append(f"Missing required {kind} artifact file: {name}")

    first = rows[0]
    run_params = _json_value(first[13])
    run_metadata = {
        "run_id": first[1],
        "status": first[11],
        "as_of_date": first[12],
        "source_run_id": _run_source_run_id(run_params),
        "params": run_params,
        "config_hash": first[14],
        "data_snapshot_id": first[15],
        "git_sha": first[16],
        "worktree_clean": first[17],
        "started_at": first[18],
        "finished_at": first[19],
        "error": first[20],
    }
    return ArtifactBundle(
        kind=kind,
        requested_run_id=run_id,
        run_id=str(resolved_run_id),
        files=files,
        file_display=display,
        artifact_rows=artifact_rows,
        run_metadata=run_metadata,
        resolved_via=resolved_via,
        warnings=tuple(warnings),
    )


def read_artifact_csv(
    bundle: ArtifactBundle,
    filename: str,
    columns: Sequence[str] = (),
    *,
    required: bool = False,
) -> pd.DataFrame:
    """Read an artifact CSV or return an empty frame with stable columns."""
    path = bundle.files.get(filename)
    if path is None or not path.exists():
        if required:
            raise FileNotFoundError(
                f"{bundle.kind} artifact {bundle.run_id} is missing {filename}."
            )
        return pd.DataFrame(columns=list(columns))
    frame = pd.read_csv(path)
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    return result


def read_artifact_json(bundle: ArtifactBundle, filename: str) -> dict[str, Any]:
    path = bundle.files.get(filename)
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {"value": data}


def bundle_input_paths(bundles: Sequence[ArtifactBundle]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for bundle in bundles:
        for path in bundle.files.values():
            resolved = path.resolve()
            if resolved.exists() and resolved.is_file() and resolved not in seen:
                paths.append(resolved)
                seen.add(resolved)
    return paths


def markdown_table(frame: pd.DataFrame, *, max_rows: int | None = None) -> str:
    result = frame.head(max_rows).copy() if max_rows is not None else frame.copy()
    columns = [str(column) for column in result.columns]
    if not columns:
        return "_No columns._"
    header = "| " + " | ".join(_escape_markdown_cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| "
        + " | ".join(_escape_markdown_cell(stringify(value)) for value in row)
        + " |"
        for row in result.itertuples(index=False, name=None)
    ]
    if not rows:
        rows = ["| " + " | ".join("" for _ in columns) + " |"]
    return "\n".join([header, separator, *rows])


def ordered_frame(
    frame: pd.DataFrame,
    columns: Sequence[str],
    sort_columns: Sequence[str] = (),
) -> pd.DataFrame:
    result = frame.copy() if not frame.empty else pd.DataFrame(columns=list(columns))
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, list(columns)]
    sort_keys = [column for column in sort_columns if column in result.columns]
    if sort_keys and not result.empty:
        result = result.sort_values(sort_keys, kind="mergesort", na_position="last")
    return result.reset_index(drop=True)


def write_json(path: Path, data: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(
        json.dumps(jsonable(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fail_if_exists(paths: Sequence[Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing report file(s): " + ", ".join(existing)
        )


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if not isinstance(value, (list, tuple, dict, set, str, bytes)):
        try:
            if bool(pd.isna(value)):
                return None
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return stringify(value)
    return value


def stringify(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _latest_run_id_for_kind(connection: duckdb.DuckDBPyConnection, kind: str) -> str | None:
    row = connection.execute(
        """
        SELECT a.run_id
        FROM research_artifacts a
        LEFT JOIN research_runs r ON r.run_id = a.run_id
        WHERE a.artifact_kind = ?
          AND COALESCE(r.status, 'succeeded') = 'succeeded'
        GROUP BY a.run_id, COALESCE(r.finished_at, r.started_at)
        ORDER BY COALESCE(r.finished_at, r.started_at) DESC, a.run_id
        LIMIT 1
        """,
        [kind],
    ).fetchone()
    return str(row[0]) if row else None


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (repo_root / path).resolve()


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


def artifact_run_value(item: Mapping[str, Any], key: str) -> Any:
    """Return a top-level audited run field from an ArtifactBundle metadata row."""
    run = item.get("run")
    if not isinstance(run, Mapping):
        return None
    return run.get(key)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value if value is not None else {}


def _run_source_run_id(params: Any) -> str | None:
    if not isinstance(params, Mapping):
        return None
    value = params.get("source_run_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
