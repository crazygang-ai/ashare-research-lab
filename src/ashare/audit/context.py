"""High-level audit context used by CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Mapping

import duckdb

from ashare.audit.artifacts import build_artifact_record, artifact_records_for_paths
from ashare.audit.config import AuditConfig, DEFAULT_CONFIG_PATH, load_audit_config
from ashare.audit.fingerprint import (
    artifact_file_input,
    cli_param_input,
    config_file_input,
    data_snapshot_id,
    duckdb_table_input,
    git_state_input,
)
from ashare.audit.git import GitStatus, get_worktree_status
from ashare.audit.hashing import combined_file_hash
from ashare.audit.manifest import build_manifest, write_manifest
from ashare.audit.run_store import begin_run, complete_run, insert_artifacts, insert_inputs
from ashare.storage.db import connect, init_db


class NoopAuditContext:
    """No-op context when run tracking is disabled."""

    enabled = False
    run_id: str | None = None
    output_dir: Path | None = None
    manifest_path: Path | None = None
    warnings: list[str]

    def __init__(self, warning: str = "WARNING: audit run tracking is disabled.") -> None:
        self.warnings = [warning]

    def begin(self) -> None:
        return

    def add_input(self, row: Mapping[str, Any]) -> None:
        return

    def add_duckdb_table_input(
        self,
        table_name: str,
        *,
        source_run_id: str | None = None,
        predicate: str | None = None,
    ) -> None:
        return

    def add_artifacts(self, paths: Mapping[str, Path]) -> None:
        return

    def succeed(self) -> None:
        return

    def fail(self, error: str) -> None:
        return

    def close(self) -> None:
        return


class AuditContext:
    """Manage a single audited CLI run from running to manifest/index persistence."""

    enabled = True

    def __init__(
        self,
        *,
        command: str,
        artifact_kind: str,
        db_path: str | Path,
        run_id: str,
        run_mode: str | None,
        overwrite_run: bool,
        audit_config_path: str | Path = DEFAULT_CONFIG_PATH,
        output_dir: str | Path | None,
        as_of_date: str | None,
        source_run_id: str | None,
        params: Mapping[str, Any],
        config_paths: list[str | Path] | None = None,
        artifact_input_paths: list[str | Path] | None = None,
    ) -> None:
        self.config: AuditConfig = load_audit_config(audit_config_path)
        self.command = command
        self.artifact_kind = artifact_kind
        self.db_path = Path(db_path)
        self.run_mode = run_mode or self.config.default_run_mode
        if self.run_mode not in {"exploratory", "formal"}:
            raise ValueError("--run-mode must be one of: exploratory, formal.")
        self.run_id = run_id
        self.overwrite_run = overwrite_run
        self.as_of_date = as_of_date
        self.source_run_id = source_run_id
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.output_dir = (
            Path(output_dir).resolve()
            if output_dir is not None
            else (self.config.default_artifact_root / artifact_kind / run_id).resolve()
        )
        self.manifest_path = self.output_dir / self.config.manifest_filename
        self.git_status = get_worktree_status(
            self.config.repo_root,
            max_dirty_files=self.config.max_dirty_files,
        )
        self.warnings = list(self.git_status.warnings)
        self._validate_git_policy()

        self.params: dict[str, Any] = {
            "command": command,
            "argv": list(sys.argv),
            "run_mode": self.run_mode,
            "run_id": run_id,
            "db_path": str(db_path),
            "source_run_id": source_run_id,
            "as_of_date": as_of_date,
            "output_dir": self._display_path(self.output_dir),
            "overwrite_run": overwrite_run,
            **dict(params),
        }
        if output_dir is not None and not _is_inside(self.output_dir, self.config.repo_root):
            self.warnings.append(
                f"Artifact output_dir is outside the repository: {self.output_dir.as_posix()}"
            )

        self.config_paths = [Path(audit_config_path), *(Path(path) for path in config_paths or [])]
        self.artifact_input_paths = [Path(path) for path in artifact_input_paths or []]
        resolved_config_paths = [
            self.config.resolve_path(path) for path in self.config_paths if self.config.resolve_path(path).exists()
        ]
        self.config_hash = combined_file_hash(resolved_config_paths, repo_root=self.config.repo_root)
        self.inputs: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._begun = False
        self._seed_inputs()

    @classmethod
    def maybe(
        cls,
        **kwargs: Any,
    ) -> "AuditContext | NoopAuditContext":
        config = load_audit_config(kwargs.get("audit_config_path", DEFAULT_CONFIG_PATH))
        if not config.enabled:
            return NoopAuditContext()
        return cls(**kwargs)

    @property
    def manifest_display_path(self) -> str:
        return self._display_path(self.manifest_path)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._require_connection()

    def begin(self) -> None:
        init_db(self.db_path)
        self._connection = connect(self.db_path)
        begin_run(
            self._connection,
            run_id=self.run_id,
            as_of_date=self.as_of_date,
            params=self.params,
            config_hash=self.config_hash,
            data_snapshot_id=None,
            git_sha=self.git_status.sha,
            worktree_clean=self.git_status.worktree_clean,
            started_at=self.started_at,
            overwrite=self.overwrite_run,
        )
        self._begun = True

    def add_input(self, row: Mapping[str, Any]) -> None:
        self.inputs.append(dict(row))

    def add_duckdb_table_input(
        self,
        table_name: str,
        *,
        source_run_id: str | None = None,
        predicate: str | None = None,
    ) -> None:
        connection = self._require_connection()
        self.inputs.append(
            duckdb_table_input(
                connection=connection,
                run_id=self.run_id,
                table_name=table_name,
                source_run_id=source_run_id,
                predicate=predicate,
                created_at=datetime.now(timezone.utc),
            )
        )

    def add_artifacts(self, paths: Mapping[str, Path]) -> None:
        self.artifacts.extend(
            artifact_records_for_paths(
                repo_root=self.config.repo_root,
                run_id=self.run_id,
                artifact_kind=self.artifact_kind,
                paths=paths,
                created_at=datetime.now(timezone.utc),
                hash_files=bool(self.config.artifacts.get("hash_files", True)),
                csv_row_count_enabled=bool(self.config.artifacts.get("csv_row_count", True)),
            )
        )

    def succeed(self) -> None:
        self._finish(status="succeeded", error=None)

    def fail(self, error: str) -> None:
        if self._begun:
            self._finish(status="failed", error=error)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _finish(self, *, status: str, error: str | None) -> None:
        connection = self._require_connection()
        self.finished_at = datetime.now(timezone.utc)
        snapshot_id = data_snapshot_id(self.inputs)
        manifest = build_manifest(
            run_id=self.run_id,
            run_mode=self.run_mode,
            command=self.command,
            argv=list(sys.argv),
            db_path=str(self.db_path),
            as_of_date=self.as_of_date,
            source_run_id=self.source_run_id,
            status=status,
            started_at=self.started_at.isoformat(),
            finished_at=self.finished_at.isoformat(),
            config_hash=self.config_hash,
            data_snapshot_id=snapshot_id,
            git={
                "sha": self.git_status.sha,
                "worktree_clean": self.git_status.worktree_clean,
                "dirty_files": list(self.git_status.dirty_files),
            },
            inputs=self.inputs,
            artifacts=self.artifacts,
            warnings=self.warnings,
            error=_compact_error(error),
            overwrite_run=self.overwrite_run,
        )
        if bool(self.config.artifacts.get("write_manifest", True)):
            write_manifest(self.manifest_path, manifest)
            manifest_record = build_artifact_record(
                repo_root=self.config.repo_root,
                run_id=self.run_id,
                artifact_kind=self.artifact_kind,
                role="manifest",
                path=self.manifest_path,
                created_at=self.finished_at,
                metadata={"schema_version": manifest["schema_version"]},
                hash_file=bool(self.config.artifacts.get("hash_files", True)),
                count_csv_rows=False,
            )
            db_artifacts = [*self.artifacts, manifest_record]
        else:
            db_artifacts = list(self.artifacts)

        try:
            connection.execute("BEGIN TRANSACTION")
            insert_inputs(connection, self.inputs)
            insert_artifacts(connection, db_artifacts)
            complete_run(
                connection,
                run_id=self.run_id,
                status=status,
                params={**self.params, "manifest_path": self.manifest_display_path},
                config_hash=self.config_hash,
                data_snapshot_id=snapshot_id,
                finished_at=self.finished_at,
                error=error,
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def _seed_inputs(self) -> None:
        created_at = datetime.now(timezone.utc)
        seen_config_paths: set[Path] = set()
        for path in self.config_paths:
            resolved = self.config.resolve_path(path)
            if resolved in seen_config_paths or not resolved.exists():
                continue
            seen_config_paths.add(resolved)
            self.inputs.append(
                config_file_input(
                    repo_root=self.config.repo_root,
                    run_id=self.run_id,
                    path=resolved,
                    created_at=created_at,
                )
            )
        for path in self.artifact_input_paths:
            resolved = self.config.resolve_path(path)
            if resolved.exists() and resolved.is_file():
                self.inputs.append(
                    artifact_file_input(
                        repo_root=self.config.repo_root,
                        run_id=self.run_id,
                        path=resolved,
                        created_at=created_at,
                    )
                )
        if self.source_run_id:
            self.inputs.append(
                cli_param_input(
                    run_id=self.run_id,
                    name="source_run_id",
                    value=self.source_run_id,
                    source_run_id=self.source_run_id,
                    created_at=created_at,
                )
            )
        self.inputs.append(
            git_state_input(
                run_id=self.run_id,
                sha=self.git_status.sha,
                worktree_clean=self.git_status.worktree_clean,
                dirty_files=self.git_status.dirty_files,
                warnings=self.git_status.warnings,
                created_at=created_at,
            )
        )

    def _validate_git_policy(self) -> None:
        if self.run_mode != "formal":
            return
        requires_clean = bool(
            self.config.run_tracking.get("formal_requires_clean_worktree", True)
        )
        if not requires_clean:
            return
        if self.git_status.worktree_clean is not True:
            dirty = ", ".join(self.git_status.dirty_files[:5]) or "unknown"
            raise ValueError(
                "formal run requires a clean git worktree; dirty files: " + dirty
            )
        if self.git_status.sha is None:
            raise ValueError("formal run requires a git repository with a readable HEAD sha.")

    def _require_connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            raise RuntimeError("Audit run has not been started.")
        return self._connection

    def _display_path(self, path: Path) -> str:
        return self.config.repo_relative(path)


def generated_run_id(command: str, git_status: GitStatus | None = None) -> str:
    status = git_status or get_worktree_status(Path.cwd())
    sha = (status.sha or "nogit")[:8]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{command}-{timestamp}-{sha}"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _compact_error(error: str | None) -> str | None:
    if error is None:
        return None
    return " ".join(str(error).split())[:1000]
