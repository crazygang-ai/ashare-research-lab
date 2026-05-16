"""Stable hashing and file metadata helpers for audit records."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return sha256_text(stable_json(value))


def combined_file_hash(paths: Iterable[Path], *, repo_root: Path | None = None) -> str:
    parts: list[dict[str, str]] = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            continue
        display = _display_path(resolved, repo_root)
        parts.append({"path": display, "sha256": sha256_file(resolved)})
    return sha256_json(sorted(parts, key=lambda item: item["path"]))


def file_size(path: str | Path) -> int:
    return Path(path).stat().st_size


def csv_row_count(path: str | Path) -> int | None:
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            rows = sum(1 for _ in reader)
        return max(0, rows - 1)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def media_type_for_path(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _display_path(path: Path, repo_root: Path | None) -> str:
    if repo_root is None:
        return path.as_posix()
    try:
        return path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return value
