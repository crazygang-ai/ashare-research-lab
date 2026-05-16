"""Configuration loading for Phase 5 run audit."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ashare.service.config import find_repo_root


EXPECTED_VERSION = "phase5.v1"
DEFAULT_CONFIG_PATH = Path("configs/audit.yaml")

DEFAULT_AUDIT_CONFIG: dict[str, Any] = {
    "version": EXPECTED_VERSION,
    "run_tracking": {
        "enabled": True,
        "default_run_mode": "exploratory",
        "formal_requires_clean_worktree": True,
        "fail_on_duplicate_run_id": True,
        "manifest_filename": "run_manifest.json",
    },
    "artifacts": {
        "default_root": "data/reports/generated",
        "write_manifest": True,
        "index_files": True,
        "hash_files": True,
        "csv_row_count": True,
    },
    "data_fingerprint": {
        "full_file_hash": True,
        "duckdb_table_mode": "metadata",
        "max_dirty_files": 50,
    },
    "factor_values": {
        "duplicate_policy": "fail",
        "overwrite_requires_flag": True,
    },
}


@dataclass(frozen=True)
class AuditConfig:
    """Validated audit configuration with repository path helpers."""

    data: dict[str, Any]
    repo_root: Path
    config_path: Path

    @property
    def run_tracking(self) -> dict[str, Any]:
        return self.data["run_tracking"]

    @property
    def artifacts(self) -> dict[str, Any]:
        return self.data["artifacts"]

    @property
    def data_fingerprint(self) -> dict[str, Any]:
        return self.data["data_fingerprint"]

    @property
    def factor_values(self) -> dict[str, Any]:
        return self.data["factor_values"]

    @property
    def enabled(self) -> bool:
        return bool(self.run_tracking.get("enabled", True))

    @property
    def default_run_mode(self) -> str:
        return str(self.run_tracking.get("default_run_mode", "exploratory"))

    @property
    def manifest_filename(self) -> str:
        return str(self.run_tracking.get("manifest_filename", "run_manifest.json"))

    @property
    def default_artifact_root(self) -> Path:
        return self.resolve_path(str(self.artifacts.get("default_root", "data/reports/generated")))

    @property
    def max_dirty_files(self) -> int:
        return int(self.data_fingerprint.get("max_dirty_files", 50))

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path.resolve()
        return (self.repo_root / path).resolve()

    def repo_relative(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.repo_root).as_posix()
        except ValueError:
            return resolved.as_posix()


def load_audit_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> AuditConfig:
    """Load, merge, and validate the Phase 5 audit configuration."""

    path = Path(config_path)
    repo_root = find_repo_root(path)
    loaded: dict[str, Any] = {}
    resolved = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    if resolved.exists():
        with resolved.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        if not isinstance(raw, dict):
            raise ValueError("audit config must be a YAML mapping.")
        loaded = raw

    merged = _deep_merge(DEFAULT_AUDIT_CONFIG, loaded)
    _validate_audit_config(merged)
    return AuditConfig(data=merged, repo_root=repo_root, config_path=resolved)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = deepcopy(value)
    return result


def _validate_audit_config(config: Mapping[str, Any]) -> None:
    if config.get("version") != EXPECTED_VERSION:
        raise ValueError(f"audit config version must be {EXPECTED_VERSION}.")
    for section in ["run_tracking", "artifacts", "data_fingerprint", "factor_values"]:
        if section not in config or not isinstance(config[section], dict):
            raise ValueError(f"audit config section {section!r} must be a mapping.")
    run_mode = str(config["run_tracking"].get("default_run_mode", ""))
    if run_mode not in {"exploratory", "formal"}:
        raise ValueError("audit default_run_mode must be exploratory or formal.")
    table_mode = str(config["data_fingerprint"].get("duckdb_table_mode", ""))
    if table_mode != "metadata":
        raise ValueError("audit duckdb_table_mode must be metadata for Phase 5.")
    duplicate_policy = str(config["factor_values"].get("duplicate_policy", ""))
    if duplicate_policy != "fail":
        raise ValueError("audit factor_values.duplicate_policy must be fail for Phase 5.")
    _assert_no_secret_keys(config)


def _assert_no_secret_keys(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lower = str(key).lower()
            if any(marker in lower for marker in ["password", "secret", "api_key", "access_key"]):
                raise ValueError(f"audit config must not contain secret-like key: {'.'.join((*path, str(key)))}")
            _assert_no_secret_keys(item, (*path, str(key)))
