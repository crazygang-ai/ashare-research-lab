from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ashare.service.config import load_service_config
from ashare.service.workflows import (
    WorkflowDatabaseConflictError,
    run_workflow,
    workflow_target_db_paths,
)


def test_workflow_dry_run_returns_plan_and_does_not_execute(tmp_path: Path) -> None:
    config_path = _workflow_config(tmp_path, command=[sys.executable, "-c", "raise SystemExit(9)"])
    config = load_service_config(config_path)

    result = run_workflow(config, "demo", dry_run=True, source="service-workflow-cli")

    assert result["status"] == "planned"
    assert result["steps"][0]["command"][0] == sys.executable
    assert not (tmp_path / "data" / "service" / "workflow-runs").exists()


def test_workflow_execute_uses_shell_false_and_writes_log(monkeypatch, tmp_path: Path) -> None:
    config_path = _workflow_config(tmp_path, command=[sys.executable, "-c", "print('ok')"])
    config = load_service_config(config_path)
    observed: dict[str, object] = {}
    real_run = subprocess.run

    def spy_run(*args, **kwargs):
        observed["shell"] = kwargs.get("shell")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)
    result = run_workflow(config, "demo", dry_run=False, source="service-workflow-cli")

    assert observed["shell"] is False
    assert result["status"] == "success"
    log_path = config.repo_root / result["log_path"]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["source"] == "service-workflow-cli"
    assert log["steps"][0]["stdout"] == "ok\n"


def test_workflow_failure_and_timeout_stop_later_steps(tmp_path: Path) -> None:
    config_path = _workflow_config(
        tmp_path,
        steps=[
            {"name": "fail", "timeout_seconds": 5, "command": [sys.executable, "-c", "raise SystemExit(3)"]},
            {"name": "skip", "timeout_seconds": 5, "command": [sys.executable, "-c", "print('skip')"]},
        ],
    )
    config = load_service_config(config_path)

    failed = run_workflow(config, "demo", dry_run=False, source="service-workflow-cli")

    assert failed["status"] == "failed"
    assert len(failed["steps"]) == 1

    timeout_config = _workflow_config(
        tmp_path / "timeout",
        steps=[
            {"name": "timeout", "timeout_seconds": 1, "command": [sys.executable, "-c", "import time; time.sleep(5)"]},
            {"name": "skip", "timeout_seconds": 5, "command": [sys.executable, "-c", "print('skip')"]},
        ],
    )
    timed_out = run_workflow(
        load_service_config(timeout_config),
        "demo",
        dry_run=False,
        source="service-workflow-cli",
    )

    assert timed_out["status"] == "timeout"
    assert timed_out["steps"][0]["timed_out"] is True
    assert len(timed_out["steps"]) == 1


def test_workflow_db_conflict_fails_execute_and_warns_dry_run(tmp_path: Path) -> None:
    config_path = _workflow_config(
        tmp_path,
        service_db="data/processed/same.duckdb",
        command=["ashare", "ingest-local", "--db-path", "data/processed/same.duckdb"],
    )
    config = load_service_config(config_path)

    plan = run_workflow(config, "demo", dry_run=True, source="service-workflow-cli")

    assert plan["warnings"]
    with pytest.raises(WorkflowDatabaseConflictError):
        run_workflow(config, "demo", dry_run=False, source="service-workflow-cli")


def test_workflow_target_db_paths_are_reported(tmp_path: Path) -> None:
    config_path = _workflow_config(
        tmp_path,
        command=["ashare", "ingest-local", "--db-path=data/processed/workflow.duckdb"],
    )
    config = load_service_config(config_path)

    assert workflow_target_db_paths(config)["demo"] == ["data/processed/workflow.duckdb"]


def _workflow_config(
    root: Path,
    *,
    command: list[str] | None = None,
    steps: list[dict[str, object]] | None = None,
    service_db: str = "data/processed/service.duckdb",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "service.yaml"
    if steps is None:
        steps = [
            {
                "name": "one",
                "timeout_seconds": 5,
                "command": command or [sys.executable, "-c", "print('ok')"],
            }
        ]
    rendered_steps = "\n".join(
        [
            "      - name: {name}\n        timeout_seconds: {timeout}\n        command:\n{command}".format(
                name=step["name"],
                timeout=step["timeout_seconds"],
                command="\n".join(f"          - {item}" for item in step["command"]),
            )
            for step in steps
        ]
    )
    path.write_text(
        f"""
version: phase4.v1
database:
  db_path: {service_db}
  read_only: true
artifacts:
  roots:
    - data/reports/generated
workflows:
  demo:
    enabled: true
    defaults:
      timeout_seconds: 5
    steps:
{rendered_steps}
""".lstrip(),
        encoding="utf-8",
    )
    return path
