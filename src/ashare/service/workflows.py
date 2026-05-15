"""Configured workflow runner used by CLI, HTTP API, and scheduler."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping

from ashare.service.config import ServiceConfig
from ashare.service.schemas import jsonable


DEFAULT_STEP_TIMEOUT_SECONDS = 1800


class WorkflowError(RuntimeError):
    """Base workflow runner error."""


class WorkflowNotFoundError(WorkflowError):
    """Raised when a workflow name is not configured."""


class WorkflowDisabledError(WorkflowError):
    """Raised when execution is requested for a disabled workflow."""


class WorkflowDatabaseConflictError(WorkflowError):
    """Raised when a workflow writes the service query DB path."""


def workflow_target_db_paths(
    config: ServiceConfig,
    workflow_name: str | None = None,
) -> dict[str, list[str]]:
    names = [workflow_name] if workflow_name is not None else sorted(config.workflows)
    result: dict[str, list[str]] = {}
    for name in names:
        workflow = config.workflows.get(name)
        if not isinstance(workflow, Mapping):
            continue
        targets: list[str] = []
        for step in workflow.get("steps", []):
            if not isinstance(step, Mapping):
                continue
            command = step.get("command", [])
            if not isinstance(command, list):
                continue
            for path in _db_paths_from_command([str(item) for item in command], config):
                display = config.repo_relative(path)
                if display not in targets:
                    targets.append(display)
        result[name] = targets
    return result


def run_workflow(
    config: ServiceConfig,
    workflow_name: str,
    *,
    dry_run: bool,
    source: str,
    allow_disabled_dry_run: bool = True,
) -> dict[str, Any]:
    workflow = config.workflows.get(workflow_name)
    if not isinstance(workflow, Mapping):
        raise WorkflowNotFoundError(f"Unknown workflow: {workflow_name}")
    enabled = bool(workflow.get("enabled", False))
    if not enabled and not (dry_run and allow_disabled_dry_run):
        raise WorkflowDisabledError(f"Workflow is disabled: {workflow_name}")

    steps = _workflow_steps(config, workflow_name, workflow)
    target_db_paths = workflow_target_db_paths(config, workflow_name).get(workflow_name, [])
    conflicts = _conflicting_target_paths(config, target_db_paths)
    warnings: list[str] = []
    if conflicts:
        warning = (
            "workflow target DB path conflicts with service query DB: "
            + ", ".join(conflicts)
        )
        if dry_run:
            warnings.append(warning)
        else:
            raise WorkflowDatabaseConflictError(warning)

    started_at = _now()
    base: dict[str, Any] = {
        "workflow_name": workflow_name,
        "source": source,
        "dry_run": dry_run,
        "enabled": enabled,
        "status": "planned" if dry_run else "running",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "target_db_paths": target_db_paths,
        "warnings": warnings,
        "steps": steps,
    }
    if dry_run:
        base["finished_at"] = _now()
        base["duration_seconds"] = 0.0
        return base

    monotonic_started = time.monotonic()
    executed_steps: list[dict[str, Any]] = []
    status = "success"
    for step in steps:
        executed = _run_step(step, config.repo_root)
        executed_steps.append(executed)
        if executed["status"] != "success":
            status = executed["status"]
            break
    finished_at = _now()
    base["steps"] = executed_steps
    base["status"] = status
    base["finished_at"] = finished_at
    base["duration_seconds"] = round(time.monotonic() - monotonic_started, 6)
    log_path = write_workflow_log(config, base)
    base["log_path"] = config.repo_relative(log_path)
    return base


def write_workflow_log(config: ServiceConfig, payload: Mapping[str, Any]) -> Path:
    log_dir = config.workflow_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = _run_id(str(payload.get("workflow_name", "workflow")), str(payload.get("source", "run")))
    log_path = log_dir / f"{run_id}.json"
    log_path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return log_path


def _workflow_steps(
    config: ServiceConfig,
    workflow_name: str,
    workflow: Mapping[str, Any],
) -> list[dict[str, Any]]:
    defaults = workflow.get("defaults", {})
    default_timeout = DEFAULT_STEP_TIMEOUT_SECONDS
    if isinstance(defaults, Mapping) and defaults.get("timeout_seconds") is not None:
        default_timeout = int(defaults["timeout_seconds"])
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(workflow.get("steps", [])):
        if not isinstance(step, Mapping):
            raise ValueError(f"workflow {workflow_name} step {index} must be a mapping.")
        command = step.get("command")
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError(f"workflow {workflow_name} step {index} command must be list[str].")
        timeout_seconds = int(step.get("timeout_seconds", default_timeout))
        steps.append(
            {
                "name": str(step.get("name", f"step-{index + 1}")),
                "command": list(command),
                "timeout_seconds": timeout_seconds,
                "target_db_paths": [
                    config.repo_relative(path)
                    for path in _db_paths_from_command(list(command), config)
                ],
            }
        )
    return steps


def _run_step(step: Mapping[str, Any], cwd: Path) -> dict[str, Any]:
    started_at = _now()
    monotonic_started = time.monotonic()
    command = [str(item) for item in step["command"]]
    timeout_seconds = int(step["timeout_seconds"])
    result: dict[str, Any] = {
        "name": step["name"],
        "command": command,
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "stdout": "",
        "stderr": "",
        "return_code": None,
        "timed_out": False,
        "status": "running",
        "target_db_paths": list(step.get("target_db_paths", [])),
    }
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        result.update(
            {
                "finished_at": _now(),
                "duration_seconds": round(time.monotonic() - monotonic_started, 6),
                "stdout": _coerce_output(exc.stdout),
                "stderr": _coerce_output(exc.stderr),
                "return_code": None,
                "timed_out": True,
                "status": "timeout",
            }
        )
        return result
    result.update(
        {
            "finished_at": _now(),
            "duration_seconds": round(time.monotonic() - monotonic_started, 6),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "return_code": completed.returncode,
            "status": "success" if completed.returncode == 0 else "failed",
        }
    )
    return result


def _db_paths_from_command(command: list[str], config: ServiceConfig) -> list[Path]:
    paths: list[Path] = []
    index = 0
    while index < len(command):
        item = command[index]
        if item == "--db-path" and index + 1 < len(command):
            paths.append(config.resolve_path(command[index + 1]))
            index += 2
            continue
        if item.startswith("--db-path="):
            paths.append(config.resolve_path(item.split("=", 1)[1]))
        index += 1
    return paths


def _conflicting_target_paths(config: ServiceConfig, target_db_paths: list[str]) -> list[str]:
    service_db = config.database_path.resolve()
    conflicts: list[str] = []
    for target in target_db_paths:
        resolved = config.resolve_path(target)
        if resolved == service_db:
            conflicts.append(target)
    return conflicts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _run_id(workflow_name: str, source: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{workflow_name}-{source}").strip("-")
    return f"{timestamp}-{safe}"


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
