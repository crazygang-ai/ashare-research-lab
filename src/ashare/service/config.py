"""Configuration loading for the Phase 4 local service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


EXPECTED_VERSION = "phase4.v1"
DEFAULT_CONFIG_PATH = Path("configs/service.yaml")
KNOWN_ARTIFACT_KINDS = ("scan", "scoring", "backtest", "factor_validation")

_DEFAULT_CONFIG: dict[str, Any] = {
    "version": EXPECTED_VERSION,
    "server": {"host": "127.0.0.1", "port": 8008, "reload": False},
    "database": {"db_path": "data/processed/ashare_phase4.duckdb", "read_only": True},
    "artifacts": {
        "roots": ["data/reports/generated"],
        "known_kinds": list(KNOWN_ARTIFACT_KINDS),
    },
    "security": {
        "allow_http_workflow_run": False,
        "require_token_for_workflows": True,
        "token_env_var": "ASHARE_SERVICE_TOKEN",
        "token_header": "X-Ashare-Token",
    },
    "scheduler": {"enabled": False, "timezone": "Asia/Shanghai"},
    "workflows": {},
}

_ALLOWED_TOKEN_CONFIG_KEYS = {
    "allow_http_workflow_run",
    "require_token_for_workflows",
    "token_env_var",
    "token_header",
}


@dataclass(frozen=True)
class ServiceConfig:
    """Validated service configuration with repository-relative path helpers."""

    data: dict[str, Any]
    repo_root: Path
    config_path: Path

    @property
    def version(self) -> str:
        return str(self.data["version"])

    @property
    def server(self) -> dict[str, Any]:
        return self.data["server"]

    @property
    def database(self) -> dict[str, Any]:
        return self.data["database"]

    @property
    def artifacts(self) -> dict[str, Any]:
        return self.data["artifacts"]

    @property
    def security(self) -> dict[str, Any]:
        return self.data["security"]

    @property
    def scheduler(self) -> dict[str, Any]:
        return self.data["scheduler"]

    @property
    def workflows(self) -> dict[str, Any]:
        return self.data["workflows"]

    @property
    def host(self) -> str:
        return str(self.server["host"])

    @property
    def port(self) -> int:
        return int(self.server["port"])

    @property
    def reload(self) -> bool:
        return bool(self.server.get("reload", False))

    @property
    def database_path(self) -> Path:
        return self.resolve_path(self.database["db_path"])

    @property
    def database_read_only(self) -> bool:
        return bool(self.database.get("read_only", True))

    @property
    def artifact_roots(self) -> tuple[Path, ...]:
        return tuple(self.resolve_path(root) for root in self.artifacts.get("roots", []))

    @property
    def known_artifact_kinds(self) -> tuple[str, ...]:
        return tuple(str(kind) for kind in self.artifacts.get("known_kinds", []))

    @property
    def scheduler_enabled(self) -> bool:
        return bool(self.scheduler.get("enabled", False))

    @property
    def scheduler_timezone(self) -> str:
        return str(self.scheduler.get("timezone", "Asia/Shanghai"))

    @property
    def workflow_log_dir(self) -> Path:
        return self.resolve_path("data/service/workflow-runs")

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


def load_service_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    overrides: Mapping[str, object] | None = None,
) -> ServiceConfig:
    """Load, merge, and validate service configuration."""

    resolved_config_path = Path(config_path)
    repo_root = find_repo_root(resolved_config_path)
    loaded: dict[str, Any] = {}
    if resolved_config_path.exists():
        with resolved_config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        if not isinstance(raw, dict):
            raise ValueError("service config must be a YAML mapping.")
        loaded = raw

    merged = _deep_merge(_DEFAULT_CONFIG, loaded)
    if overrides:
        merged = _deep_merge(merged, dict(overrides))

    _validate_service_config(merged)
    return ServiceConfig(
        data=merged,
        repo_root=repo_root,
        config_path=(repo_root / resolved_config_path).resolve()
        if not resolved_config_path.is_absolute()
        else resolved_config_path.resolve(),
    )


def find_repo_root(config_path: str | Path | None = None) -> Path:
    """Find the repository root from a config path or the current directory."""

    start = Path(config_path).resolve() if config_path is not None else Path.cwd().resolve()
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        pyproject = candidate / "pyproject.toml"
        if pyproject.exists() and (candidate / "src" / "ashare").exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = deepcopy(value)
    return result


def _validate_service_config(config: Mapping[str, Any]) -> None:
    if config.get("version") != EXPECTED_VERSION:
        raise ValueError(f"service config version must be {EXPECTED_VERSION}.")
    for section in ["server", "database", "artifacts", "security", "scheduler", "workflows"]:
        if section not in config or not isinstance(config[section], dict):
            raise ValueError(f"service config section {section!r} must be a mapping.")
    if str(config["server"].get("host", "")) != "127.0.0.1":
        # Overrides may intentionally change the host, but the checked-in default must stay local.
        pass
    if bool(config["database"].get("read_only", True)) is not True:
        raise ValueError("service database.read_only must default to true.")
    if not isinstance(config["artifacts"].get("roots"), list):
        raise ValueError("service artifacts.roots must be a list.")
    kinds = tuple(str(kind) for kind in config["artifacts"].get("known_kinds", []))
    unknown = sorted(set(kinds).difference(KNOWN_ARTIFACT_KINDS))
    if unknown:
        raise ValueError(f"Unknown service artifact kind(s): {', '.join(unknown)}")
    _assert_no_plaintext_secrets(config)
    _validate_workflows(config["workflows"])


def _validate_workflows(workflows: Mapping[str, Any]) -> None:
    for name, workflow in workflows.items():
        if not isinstance(workflow, Mapping):
            raise ValueError(f"workflow {name!r} must be a mapping.")
        steps = workflow.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError(f"workflow {name!r} steps must be a list.")
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise ValueError(f"workflow {name!r} step {index} must be a mapping.")
            command = step.get("command")
            if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                raise ValueError(f"workflow {name!r} step {index} command must be list[str].")


def _assert_no_plaintext_secrets(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_no_plaintext_secrets(item, (*path, str(key)))
        return
    if not path:
        return
    key = path[-1].lower()
    if key in _ALLOWED_TOKEN_CONFIG_KEYS:
        return
    if any(marker in key for marker in ["password", "secret", "api_key", "access_key"]):
        if isinstance(value, str) and value.strip():
            dotted = ".".join(path)
            raise ValueError(f"service config must not contain plaintext secret at {dotted}.")
