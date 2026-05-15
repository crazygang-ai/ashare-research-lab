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
}

ARTIFACT_MARKDOWN_FILES = {
    "scan": "candidate_list.md",
    "scoring": "scoring_report.md",
    "backtest": "backtest_report.md",
    "factor_validation": "factor_validation_report.md",
}

ARTIFACT_PRIMARY_CSV = {
    "scan": "candidates.csv",
    "scoring": "scored_candidates.csv",
    "backtest": "metrics.csv",
    "factor_validation": "ic_summary.csv",
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "title": self.title,
            "output_dir": self.output_dir_display,
            "files": self.file_display,
            "metadata": jsonable(self.metadata),
            "warnings": list(self.warnings),
            "updated_at": self.updated_at,
        }


class ArtifactRegistry:
    """Scan configured artifact roots and expose stable id based lookup."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config

    def list_artifacts(self, kind: str | None = None, limit: int | None = None) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
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
            if record.artifact_id == artifact_id:
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
                required = set(ARTIFACT_REQUIRED_FILES[kind])
                if not required.intersection(present):
                    continue
                records.append(self._build_record(kind, directory, resolved_root, present))
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


def _artifact_id(kind: str, output_dir_display: str) -> str:
    source = f"{kind}|{output_dir_display}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


def _looks_like_artifact_id(value: str) -> bool:
    return len(value) == 12 and all(char in "0123456789abcdef" for char in value)


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
