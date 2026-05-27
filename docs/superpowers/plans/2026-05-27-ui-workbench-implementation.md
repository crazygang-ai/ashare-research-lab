# UI Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local React/Vite research workbench that reviews existing ashare artifacts and can trigger controlled stock-report and HS300 daily workflow runs through FastAPI.

**Architecture:** Keep the selected two-service architecture: FastAPI remains the backend API at `127.0.0.1:8008`, and a new `frontend/` Vite React app runs at `127.0.0.1:5173`. Mutating UI tasks are executed by a new backend UI runner that writes JSON task history and log files under `data/service/`, while research artifacts continue to be created by existing CLI/audit code.

**Tech Stack:** FastAPI, DuckDB, Typer CLI, Python subprocess with `shell=False`, Server-Sent Events, React, TypeScript, Vite, React Router, TanStack Query, TanStack Table, react-markdown, lucide-react, Tailwind CSS, pytest, Vitest.

---

## Scope Check

The spec spans backend task execution, backend API endpoints, and a standalone frontend. These are interdependent because the frontend is not useful without the UI task API, and the UI task API needs frontend consumers to validate shape. Keep one plan, but commit after each task so backend-only progress remains usable.

## File Structure

Create or modify these files:

- Modify: `configs/service.yaml`
  Adds safe default `ui_runner` configuration.
- Modify: `src/ashare/service/config.py`
  Loads and validates `ui_runner`; exposes history/log path helpers.
- Create: `src/ashare/service/ui_runs.py`
  Owns UI task models, task history JSON, subprocess execution, concurrency lock, command building, and log event streaming.
- Modify: `src/ashare/service/app.py`
  Adds `/api/v1/ui/*` endpoints and SSE response wiring.
- Modify: `src/ashare/service/schemas.py`
  Adds helpers only if needed for JSON/SSE serialization.
- Create: `tests/test_service_ui_runs.py`
  Unit tests for runner config, command construction, history, logs, concurrency, and failed subprocess state.
- Modify: `tests/test_service_config.py`
  Covers `ui_runner` defaults and overrides.
- Modify: `tests/test_service_api.py`
  Covers UI config endpoint, disabled runner rejection, enabled runner mock path, and run listing.
- Create: `frontend/package.json`
  Frontend scripts and dependencies.
- Create: `frontend/index.html`
  Vite entry HTML.
- Create: `frontend/src/main.tsx`
  React bootstrap.
- Create: `frontend/src/App.tsx`
  Router and app shell composition.
- Create: `frontend/src/api/client.ts`
  API client wrappers and typed DTOs.
- Create: `frontend/src/api/logStream.ts`
  SSE log stream helper.
- Create: `frontend/src/components/AppShell.tsx`
  Sidebar, topbar, research-only banner, and layout frame.
- Create: `frontend/src/components/StatusBadge.tsx`
  Shared status rendering.
- Create: `frontend/src/components/ArtifactTable.tsx`
  Artifact registry table.
- Create: `frontend/src/components/ReportViewer.tsx`
  Markdown and CSV report reader.
- Create: `frontend/src/components/RunTimeline.tsx`
  Step timeline.
- Create: `frontend/src/components/LogStream.tsx`
  Live stdout/stderr pane.
- Create: `frontend/src/components/CommandPreview.tsx`
  Copyable command preview.
- Create: `frontend/src/pages/TodayPage.tsx`
  Daily review landing page.
- Create: `frontend/src/pages/StocksPage.tsx`
  Single-stock lookup and stock-report trigger.
- Create: `frontend/src/pages/ReportsPage.tsx`
  Report browser.
- Create: `frontend/src/pages/RunsPage.tsx`
  UI task history and detail.
- Create: `frontend/src/pages/ArtifactsPage.tsx`
  Artifact registry browser.
- Create: `frontend/src/pages/SettingsPage.tsx`
  Local frontend/API settings display.
- Create: `frontend/src/styles.css`
  Tailwind base and small app-specific utilities.
- Create: `frontend/vite.config.ts`
  Vite React config with `/api` proxy.
- Create: `frontend/tailwind.config.ts`
  Tailwind content paths.
- Create: `frontend/postcss.config.js`
  Tailwind PostCSS setup.
- Create: `frontend/tsconfig.json`
  TypeScript config.
- Create: `frontend/src/__tests__/App.test.tsx`
  Frontend smoke tests with mocked API calls.
- Modify: `.gitignore`
  Ignore frontend build outputs and node modules.
- Modify: `README.md`
  Add local UI startup commands and research boundary notes.

## Task 1: Backend UI Runner Configuration

**Files:**
- Modify: `configs/service.yaml`
- Modify: `src/ashare/service/config.py`
- Modify: `tests/test_service_config.py`

- [ ] **Step 1: Write failing config tests**

Add these tests to `tests/test_service_config.py`:

```python
def test_service_config_loads_ui_runner_defaults() -> None:
    config = load_service_config("configs/service.yaml")

    assert config.ui_runner["enabled"] is False
    assert config.ui_runner_enabled is False
    assert config.ui_runner_max_concurrent_runs == 1
    assert config.ui_runner_history_dir == (
        config.repo_root / "data/service/workflow-runs"
    ).resolve()
    assert config.ui_runner_log_dir == (
        config.repo_root / "data/service/workflow-logs"
    ).resolve()
    assert config.ui_runner_allowed_commands == ("stock-report", "hs300-daily")


def test_service_config_rejects_unknown_ui_runner_command(tmp_path: Path) -> None:
    path = tmp_path / "service.yaml"
    path.write_text(
        """
version: phase4.v1
ui_runner:
  allowed_commands:
    - shell
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown ui_runner allowed command"):
        load_service_config(path)
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_config.py
```

Expected: fail because `ServiceConfig` has no `ui_runner` properties.

- [ ] **Step 3: Add service config defaults**

In `src/ashare/service/config.py`, add `ui_runner` to `_DEFAULT_CONFIG`:

```python
    "ui_runner": {
        "enabled": False,
        "max_concurrent_runs": 1,
        "history_dir": "data/service/workflow-runs",
        "log_dir": "data/service/workflow-logs",
        "require_confirmation": True,
        "allowed_commands": ["stock-report", "hs300-daily"],
    },
```

Update the required section list in `_validate_service_config`:

```python
    for section in [
        "server",
        "database",
        "artifacts",
        "security",
        "scheduler",
        "workflows",
        "ui_runner",
    ]:
```

Add this constant near `_ALLOWED_TOKEN_CONFIG_KEYS`:

```python
_ALLOWED_UI_RUNNER_COMMANDS = {"stock-report", "hs300-daily"}
```

Add these properties to `ServiceConfig`:

```python
    @property
    def ui_runner(self) -> dict[str, Any]:
        return self.data["ui_runner"]

    @property
    def ui_runner_enabled(self) -> bool:
        return bool(self.ui_runner.get("enabled", False))

    @property
    def ui_runner_max_concurrent_runs(self) -> int:
        return int(self.ui_runner.get("max_concurrent_runs", 1))

    @property
    def ui_runner_history_dir(self) -> Path:
        return self.resolve_path(self.ui_runner.get("history_dir", "data/service/workflow-runs"))

    @property
    def ui_runner_log_dir(self) -> Path:
        return self.resolve_path(self.ui_runner.get("log_dir", "data/service/workflow-logs"))

    @property
    def ui_runner_require_confirmation(self) -> bool:
        return bool(self.ui_runner.get("require_confirmation", True))

    @property
    def ui_runner_allowed_commands(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.ui_runner.get("allowed_commands", []))
```

Add validation:

```python
def _validate_ui_runner(config: Mapping[str, Any]) -> None:
    ui_runner = config["ui_runner"]
    if not isinstance(ui_runner.get("enabled", False), bool):
        raise ValueError("service ui_runner.enabled must be a boolean.")
    max_runs = int(ui_runner.get("max_concurrent_runs", 1))
    if max_runs != 1:
        raise ValueError("service ui_runner.max_concurrent_runs must be 1 for the MVP.")
    for key in ["history_dir", "log_dir"]:
        if not str(ui_runner.get(key, "")).strip():
            raise ValueError(f"service ui_runner.{key} must be non-empty.")
    allowed = tuple(str(item) for item in ui_runner.get("allowed_commands", []))
    unknown = sorted(set(allowed).difference(_ALLOWED_UI_RUNNER_COMMANDS))
    if unknown:
        raise ValueError("Unknown ui_runner allowed command(s): " + ", ".join(unknown))
```

Call `_validate_ui_runner(config)` from `_validate_service_config` after `_validate_workflows(...)`.

- [ ] **Step 4: Update checked-in config**

Append this section to `configs/service.yaml`:

```yaml
ui_runner:
  enabled: false
  max_concurrent_runs: 1
  history_dir: data/service/workflow-runs
  log_dir: data/service/workflow-logs
  require_confirmation: true
  allowed_commands:
    - stock-report
    - hs300-daily
```

- [ ] **Step 5: Run the config tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_config.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add configs/service.yaml src/ashare/service/config.py tests/test_service_config.py
git commit -m "feat: add service ui runner config"
```

## Task 2: Backend UI Run Store And Command Builder

**Files:**
- Create: `src/ashare/service/ui_runs.py`
- Create: `tests/test_service_ui_runs.py`

- [ ] **Step 1: Write failing unit tests for run store and commands**

Create `tests/test_service_ui_runs.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

from ashare.service.config import load_service_config
from ashare.service.ui_runs import (
    Hs300DailyRunRequest,
    StockReportRunRequest,
    UIRunStatus,
    build_hs300_daily_command,
    build_stock_report_command,
    create_ui_run,
    list_ui_runs,
)


def test_create_ui_run_writes_json_history(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = StockReportRunRequest(
        stock_code="002594.SZ",
        as_of="2026-05-22",
        source_run_id="hs300-factor-20260522",
        score_run_id="hs300-score-20260522",
        scan_run_id="hs300-scan-20260522",
        db_path="data/processed/hs300_daily.duckdb",
        output_dir="data/reports/generated/ui/stock-002594-SZ",
        run_id="ui-stock-002594-SZ-20260522",
        confirmed=True,
    )

    run = create_ui_run(config, task_type="stock-report", params=request.model_dump())

    assert run.status == UIRunStatus.QUEUED
    assert run.ui_run_id.startswith("stock-report-")
    history_path = config.ui_runner_history_dir / f"{run.ui_run_id}.json"
    payload = json.loads(history_path.read_text(encoding="utf-8"))
    assert payload["task_type"] == "stock-report"
    assert payload["params"]["stock_code"] == "002594.SZ"
    assert list_ui_runs(config)[0].ui_run_id == run.ui_run_id


def test_build_stock_report_command_is_explicit_conda_invocation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = StockReportRunRequest(
        stock_code="002594.SZ",
        as_of="2026-05-22",
        source_run_id="factor",
        score_run_id="score",
        scan_run_id="scan",
        db_path="data/processed/hs300_daily.duckdb",
        output_dir="data/reports/generated/ui/stock-002594-SZ",
        run_id="stock-ui",
        confirmed=True,
    )

    command = build_stock_report_command(config, request)

    assert command[:5] == ["conda", "run", "-n", "ashare-research-lab", "ashare"]
    assert "stock-report" in command
    assert "--code" in command
    assert "002594.SZ" in command
    assert "--overwrite-run" in command


def test_build_hs300_daily_command_includes_optional_flags(tmp_path: Path) -> None:
    config = _config(tmp_path)
    request = Hs300DailyRunRequest(
        as_of="2026-05-22",
        stock_code="002594.SZ",
        cache_mode="offline",
        max_symbols=20,
        watchlist_file="configs/watchlist.example.csv",
        confirmed=True,
    )

    command = build_hs300_daily_command(config, request)

    assert command[:2] == ["scripts/run_hs300_daily_research.sh", "--as-of"]
    assert "2026-05-22" in command
    assert "--stock-code" in command
    assert "002594.SZ" in command
    assert "--cache-mode" in command
    assert "offline" in command
    assert "--max-symbols" in command
    assert "20" in command
    assert "--watchlist-file" in command


def _config(tmp_path: Path):
    return load_service_config(
        "configs/service.yaml",
        overrides={
            "ui_runner": {
                "enabled": True,
                "history_dir": str(tmp_path / "runs"),
                "log_dir": str(tmp_path / "logs"),
            }
        },
    )
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_ui_runs.py
```

Expected: fail because `ashare.service.ui_runs` does not exist.

- [ ] **Step 3: Implement request models, status enum, run record, and JSON store**

Create `src/ashare/service/ui_runs.py` with:

```python
"""Local UI-triggered research task runner and history store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ashare.service.config import ServiceConfig
from ashare.service.schemas import jsonable


class UIRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StockReportRunRequest(BaseModel):
    stock_code: str = Field(min_length=6)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_run_id: str = Field(min_length=1)
    score_run_id: str = Field(min_length=1)
    scan_run_id: str | None = None
    db_path: str = Field(default="data/processed/hs300_daily.duckdb", min_length=1)
    output_dir: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    confirmed: bool = False

    @model_validator(mode="after")
    def require_confirmation(self) -> "StockReportRunRequest":
        if not self.confirmed:
            raise ValueError("confirmed must be true for stock-report runs.")
        return self


class Hs300DailyRunRequest(BaseModel):
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    stock_code: str = Field(default="002594.SZ", min_length=6)
    cache_mode: str = "use"
    max_symbols: int | None = Field(default=None, gt=0)
    watchlist_file: str | None = None
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_request(self) -> "Hs300DailyRunRequest":
        if self.cache_mode not in {"use", "refresh", "offline"}:
            raise ValueError("cache_mode must be one of: use, refresh, offline.")
        if not self.confirmed:
            raise ValueError("confirmed must be true for hs300-daily runs.")
        return self


@dataclass(frozen=True)
class UIRunRecord:
    ui_run_id: str
    task_type: str
    status: UIRunStatus
    params: dict[str, Any]
    command_preview: list[str]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    log_paths: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(
            {
                "ui_run_id": self.ui_run_id,
                "task_type": self.task_type,
                "status": self.status.value,
                "params": self.params,
                "command_preview": self.command_preview,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "steps": self.steps,
                "log_paths": self.log_paths,
                "artifact_paths": self.artifact_paths,
                "error_code": self.error_code,
                "error_message": self.error_message,
            }
        )


def build_stock_report_command(config: ServiceConfig, request: StockReportRunRequest) -> list[str]:
    command = [
        "conda",
        "run",
        "-n",
        "ashare-research-lab",
        "ashare",
        "stock-report",
        "--db-path",
        request.db_path,
        "--code",
        request.stock_code,
        "--as-of",
        request.as_of,
        "--source-run-id",
        request.source_run_id,
        "--score-run-id",
        request.score_run_id,
    ]
    if request.scan_run_id:
        command.extend(["--scan-run-id", request.scan_run_id])
    command.extend(
        [
            "--output-dir",
            request.output_dir,
            "--run-id",
            request.run_id,
            "--run-mode",
            "exploratory",
            "--overwrite",
            "--overwrite-run",
        ]
    )
    return command


def build_hs300_daily_command(config: ServiceConfig, request: Hs300DailyRunRequest) -> list[str]:
    command = [
        "scripts/run_hs300_daily_research.sh",
        "--as-of",
        request.as_of,
        "--stock-code",
        request.stock_code,
        "--cache-mode",
        request.cache_mode,
    ]
    if request.max_symbols is not None:
        command.extend(["--max-symbols", str(request.max_symbols)])
    if request.watchlist_file:
        command.extend(["--watchlist-file", request.watchlist_file])
    return command


def create_ui_run(config: ServiceConfig, *, task_type: str, params: dict[str, Any]) -> UIRunRecord:
    if task_type == "stock-report":
        request = StockReportRunRequest(**params)
        command = build_stock_report_command(config, request)
        params = request.model_dump()
    elif task_type == "hs300-daily":
        request = Hs300DailyRunRequest(**params)
        command = build_hs300_daily_command(config, request)
        params = request.model_dump()
    else:
        raise ValueError(f"Unsupported UI task type: {task_type}")
    run = UIRunRecord(
        ui_run_id=_new_ui_run_id(task_type),
        task_type=task_type,
        status=UIRunStatus.QUEUED,
        params=params,
        command_preview=command,
        created_at=_now(),
    )
    write_ui_run(config, run)
    return run


def write_ui_run(config: ServiceConfig, run: UIRunRecord) -> Path:
    config.ui_runner_history_dir.mkdir(parents=True, exist_ok=True)
    path = config.ui_runner_history_dir / f"{run.ui_run_id}.json"
    path.write_text(
        json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_ui_run(config: ServiceConfig, ui_run_id: str) -> UIRunRecord | None:
    path = config.ui_runner_history_dir / f"{ui_run_id}.json"
    if not path.is_file():
        return None
    return _record_from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_ui_runs(config: ServiceConfig, limit: int = 50) -> list[UIRunRecord]:
    if not config.ui_runner_history_dir.is_dir():
        return []
    records = [
        _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(config.ui_runner_history_dir.glob("*.json"), reverse=True)
    ]
    return records[:limit]


def _record_from_dict(data: dict[str, Any]) -> UIRunRecord:
    return UIRunRecord(
        ui_run_id=str(data["ui_run_id"]),
        task_type=str(data["task_type"]),
        status=UIRunStatus(str(data["status"])),
        params=dict(data.get("params", {})),
        command_preview=[str(item) for item in data.get("command_preview", [])],
        created_at=str(data["created_at"]),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        steps=list(data.get("steps", [])),
        log_paths=list(data.get("log_paths", [])),
        artifact_paths=list(data.get("artifact_paths", [])),
        error_code=data.get("error_code"),
        error_message=data.get("error_message"),
    )


def _new_ui_run_id(task_type: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_type = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_type).strip("-")
    return f"{safe_type}-{timestamp}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
```

- [ ] **Step 4: Run the unit tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_ui_runs.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ashare/service/ui_runs.py tests/test_service_ui_runs.py
git commit -m "feat: add ui run history and commands"
```

## Task 3: Backend Subprocess Runner And SSE Log Events

**Files:**
- Modify: `src/ashare/service/ui_runs.py`
- Modify: `tests/test_service_ui_runs.py`

- [ ] **Step 1: Add failing tests for execution, failure, and concurrency**

Append to `tests/test_service_ui_runs.py`:

```python
import sys
import threading
import time

import pytest

from ashare.service.ui_runs import (
    UI_RUN_LOCK,
    UIRunAlreadyRunningError,
    execute_ui_run,
    stream_log_events,
)


def test_execute_ui_run_writes_stdout_and_success(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    run = create_ui_run(
        config,
        task_type="hs300-daily",
        params={
            "as_of": "2026-05-22",
            "stock_code": "002594.SZ",
            "cache_mode": "use",
            "confirmed": True,
        },
    )
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [sys.executable, "-c", "print('hello from ui runner')"],
    )

    finished = execute_ui_run(config, run.ui_run_id)

    assert finished.status == UIRunStatus.SUCCESS
    assert finished.started_at is not None
    assert finished.finished_at is not None
    log_path = config.repo_root / finished.log_paths[0]
    assert "hello from ui runner" in log_path.read_text(encoding="utf-8")


def test_execute_ui_run_marks_failed_on_nonzero_exit(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    run = create_ui_run(
        config,
        task_type="hs300-daily",
        params={"as_of": "2026-05-22", "stock_code": "002594.SZ", "confirmed": True},
    )
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [
            sys.executable,
            "-c",
            "import sys; print('bad', file=sys.stderr); raise SystemExit(7)",
        ],
    )

    finished = execute_ui_run(config, run.ui_run_id)

    assert finished.status == UIRunStatus.FAILED
    assert finished.error_code == "command_failed"
    assert "exit code 7" in str(finished.error_message)
    log_path = config.repo_root / finished.log_paths[0]
    assert "bad" in log_path.read_text(encoding="utf-8")


def test_execute_ui_run_rejects_concurrent_mutating_task(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = create_ui_run(
        config,
        task_type="hs300-daily",
        params={"as_of": "2026-05-22", "stock_code": "002594.SZ", "confirmed": True},
    )
    second = create_ui_run(
        config,
        task_type="hs300-daily",
        params={"as_of": "2026-05-23", "stock_code": "002594.SZ", "confirmed": True},
    )
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [sys.executable, "-c", "import time; time.sleep(0.4)"],
    )
    thread = threading.Thread(target=execute_ui_run, args=(config, first.ui_run_id))
    thread.start()
    time.sleep(0.1)

    with pytest.raises(UIRunAlreadyRunningError):
        execute_ui_run(config, second.ui_run_id)

    thread.join(timeout=2)
    assert not UI_RUN_LOCK.locked()


def test_stream_log_events_reads_existing_log(tmp_path: Path) -> None:
    config = _config(tmp_path)
    run = create_ui_run(
        config,
        task_type="hs300-daily",
        params={"as_of": "2026-05-22", "stock_code": "002594.SZ", "confirmed": True},
    )
    log_dir = config.ui_runner_log_dir / run.ui_run_id
    log_dir.mkdir(parents=True)
    log_path = log_dir / "main.log"
    log_path.write_text("line one\nline two\n", encoding="utf-8")
    updated = UIRunStatus.SUCCESS

    events = list(stream_log_events(log_path, status=updated))

    assert events[0]["type"] == "log"
    assert events[0]["message"] == "line one"
    assert events[-1]["type"] == "status"
    assert events[-1]["status"] == "success"
```

- [ ] **Step 2: Run failing runner tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_ui_runs.py
```

Expected: fail because `execute_ui_run`, `stream_log_events`, and concurrency classes are missing.

- [ ] **Step 3: Implement execution and log streaming**

Add imports to `src/ashare/service/ui_runs.py`:

```python
import subprocess
import threading
```

Add:

```python
UI_RUN_LOCK = threading.Lock()


class UIRunAlreadyRunningError(RuntimeError):
    """Raised when a mutating UI run is already active."""
```

Add command resolver:

```python
def command_for_run(config: ServiceConfig, run: UIRunRecord) -> list[str]:
    if run.task_type == "stock-report":
        return build_stock_report_command(config, StockReportRunRequest(**run.params))
    if run.task_type == "hs300-daily":
        return build_hs300_daily_command(config, Hs300DailyRunRequest(**run.params))
    raise ValueError(f"Unsupported UI task type: {run.task_type}")
```

Add immutable update helper:

```python
def update_ui_run(config: ServiceConfig, run: UIRunRecord, **changes: Any) -> UIRunRecord:
    data = run.to_dict()
    data.update(jsonable(changes))
    updated = _record_from_dict(data)
    write_ui_run(config, updated)
    return updated
```

Add executor:

```python
def execute_ui_run(config: ServiceConfig, ui_run_id: str) -> UIRunRecord:
    if not UI_RUN_LOCK.acquire(blocking=False):
        raise UIRunAlreadyRunningError("A mutating UI workflow is already running.")
    try:
        run = read_ui_run(config, ui_run_id)
        if run is None:
            raise FileNotFoundError(f"UI run not found: {ui_run_id}")
        command = command_for_run(config, run)
        log_dir = config.ui_runner_log_dir / run.ui_run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "main.log"
        display_log_path = config.repo_relative(log_path)
        run = update_ui_run(
            config,
            run,
            status=UIRunStatus.RUNNING.value,
            started_at=_now(),
            command_preview=command,
            log_paths=[display_log_path],
            steps=[
                {
                    "name": run.task_type,
                    "status": UIRunStatus.RUNNING.value,
                    "command": command,
                    "started_at": _now(),
                }
            ],
        )
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(config.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
            return_code = process.wait()
        if return_code == 0:
            return update_ui_run(
                config,
                run,
                status=UIRunStatus.SUCCESS.value,
                finished_at=_now(),
                steps=[{**run.steps[0], "status": UIRunStatus.SUCCESS.value, "finished_at": _now()}],
            )
        return update_ui_run(
            config,
            run,
            status=UIRunStatus.FAILED.value,
            finished_at=_now(),
            error_code="command_failed",
            error_message=f"Command exited with exit code {return_code}.",
            steps=[{**run.steps[0], "status": UIRunStatus.FAILED.value, "finished_at": _now()}],
        )
    finally:
        UI_RUN_LOCK.release()
```

Add log event generator:

```python
def stream_log_events(log_path: Path, *, status: UIRunStatus) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            events.append({"type": "log", "message": line})
    events.append({"type": "status", "status": status.value})
    return events
```

- [ ] **Step 4: Run runner tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_ui_runs.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ashare/service/ui_runs.py tests/test_service_ui_runs.py
git commit -m "feat: execute ui runs with logs"
```

## Task 4: FastAPI UI Endpoints

**Files:**
- Modify: `src/ashare/service/app.py`
- Modify: `tests/test_service_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_service_api.py`:

```python
def test_ui_config_endpoint_reports_safe_defaults(tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(tmp_path / "ashare.duckdb")},
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    client = TestClient(app)

    response = client.get("/api/v1/ui/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["research_only"] is True
    assert payload["ui_runner"]["enabled"] is False
    assert "candidate list is not a trading instruction" in payload["research_notices"]


def test_ui_run_post_rejects_when_runner_disabled(tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "ui_runner": {"enabled": False},
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/ui/runs/stock-report",
        json={
            "stock_code": "002594.SZ",
            "as_of": "2026-05-22",
            "source_run_id": "factor",
            "score_run_id": "score",
            "scan_run_id": "scan",
            "db_path": "data/processed/hs300_daily.duckdb",
            "output_dir": "data/reports/generated/ui/stock",
            "run_id": "stock-ui",
            "confirmed": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ui_runner_disabled"


def test_ui_run_history_endpoint_lists_created_run(monkeypatch, tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "ui_runner": {
                "enabled": True,
                "history_dir": str(tmp_path / "runs"),
                "log_dir": str(tmp_path / "logs"),
            },
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    client = TestClient(app)

    created = client.post(
        "/api/v1/ui/runs/hs300-daily",
        json={
            "as_of": "2026-05-22",
            "stock_code": "002594.SZ",
            "cache_mode": "use",
            "confirmed": True,
        },
    )

    assert created.status_code == 200
    assert created.json()["run"]["status"] == "queued"
    runs = client.get("/api/v1/ui/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["task_type"] == "hs300-daily"
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_api.py
```

Expected: fail because `/api/v1/ui/config` and UI run endpoints do not exist.

- [ ] **Step 3: Add app imports**

In `src/ashare/service/app.py`, add:

```python
import json
from fastapi.responses import StreamingResponse
from ashare.service.ui_runs import (
    Hs300DailyRunRequest,
    StockReportRunRequest,
    UIRunAlreadyRunningError,
    create_ui_run,
    execute_ui_run,
    list_ui_runs,
    read_ui_run,
    stream_log_events,
)
```

- [ ] **Step 4: Add UI endpoints inside `create_app`**

Add these endpoints after `/api/v1/status`:

```python
    @app.get("/api/v1/ui/config")
    def ui_config() -> dict[str, Any]:
        return with_research_flags(
            {
                "api_base_url": "http://127.0.0.1:8008",
                "database": {
                    "db_path": config.repo_relative(config.database_path),
                    "read_only": config.database_read_only,
                    "available": database_available(config),
                },
                "artifact_roots": [config.repo_relative(root) for root in config.artifact_roots],
                "ui_runner": {
                    "enabled": config.ui_runner_enabled,
                    "history_dir": config.repo_relative(config.ui_runner_history_dir),
                    "log_dir": config.repo_relative(config.ui_runner_log_dir),
                    "allowed_commands": list(config.ui_runner_allowed_commands),
                    "require_confirmation": config.ui_runner_require_confirmation,
                },
                "research_notices": [
                    "candidate list is not a trading instruction",
                    "composite score is not a trading instruction",
                    "backtest is a historical simulation, not a performance promise",
                    "stock report is for research review only",
                    "AkShare HS300 members are a current snapshot, not strict historical PIT.",
                ],
            }
        )

    @app.post("/api/v1/ui/runs/stock-report")
    def ui_stock_report_run(payload: StockReportRunRequest) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = create_ui_run(config, task_type="stock-report", params=payload.model_dump())
        except ValueError as exc:
            return _error(422, "invalid_params", str(exc))
        return _json({"run": run.to_dict()})

    @app.post("/api/v1/ui/runs/hs300-daily")
    def ui_hs300_daily_run(payload: Hs300DailyRunRequest) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = create_ui_run(config, task_type="hs300-daily", params=payload.model_dump())
        except ValueError as exc:
            return _error(422, "invalid_params", str(exc))
        return _json({"run": run.to_dict()})

    @app.get("/api/v1/ui/runs")
    def ui_runs(limit: int = Query(50, ge=1)) -> JSONResponse:
        runs = [run.to_dict() for run in list_ui_runs(config, limit=min(limit, 100))]
        return _json({"runs": runs})

    @app.get("/api/v1/ui/runs/{ui_run_id}")
    def ui_run_detail(ui_run_id: str) -> JSONResponse:
        run = read_ui_run(config, ui_run_id)
        if run is None:
            return _error(404, "ui_run_not_found", "UI run not found.")
        return _json({"run": run.to_dict()})
```

Add an execution endpoint after the detail endpoint for MVP manual launch:

```python
    @app.post("/api/v1/ui/runs/{ui_run_id}/execute")
    def ui_run_execute(ui_run_id: str) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = execute_ui_run(config, ui_run_id)
        except UIRunAlreadyRunningError as exc:
            return _error(409, "workflow_already_running", str(exc))
        except FileNotFoundError as exc:
            return _error(404, "ui_run_not_found", str(exc))
        return _json({"run": run.to_dict()})
```

Add SSE endpoint:

```python
    @app.get("/api/v1/ui/runs/{ui_run_id}/logs/stream")
    def ui_run_log_stream(ui_run_id: str) -> Response:
        run = read_ui_run(config, ui_run_id)
        if run is None:
            return _error(404, "ui_run_not_found", "UI run not found.")
        if not run.log_paths:
            return _error(404, "log_not_found", "No log path has been recorded for this UI run.")
        log_path = config.repo_root / str(run.log_paths[0])

        def event_source():
            for event in stream_log_events(log_path, status=run.status):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

        return StreamingResponse(event_source(), media_type="text/event-stream")
```

The first frontend can create a run and execute it through `/execute`. A later enhancement can start execution in a background worker immediately after creation.

- [ ] **Step 5: Run service API tests**

Run:

```bash
conda run -n ashare-research-lab pytest -q tests/test_service_api.py tests/test_service_ui_runs.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/ashare/service/app.py tests/test_service_api.py
git commit -m "feat: add ui run api endpoints"
```

## Task 5: Frontend Project Scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Modify: `.gitignore`

- [ ] **Step 1: Create frontend package**

Create `frontend/package.json`:

```json
{
  "name": "ashare-research-lab-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host 127.0.0.1",
    "test": "vitest run",
    "lint": "eslint ."
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "@tanstack/react-table": "^8.20.5",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-markdown": "^9.0.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.15.0",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.15",
    "typescript": "^5.6.3",
    "vite": "^5.4.11",
    "vitest": "^2.1.5"
  }
}
```

- [ ] **Step 2: Create Vite config**

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8008"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts"
  }
});
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": []
}
```

- [ ] **Step 3: Create Tailwind setup**

Create `frontend/tailwind.config.ts`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#f8fafc",
        ink: "#0f172a"
      }
    }
  },
  plugins: []
} satisfies Config;
```

Create `frontend/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {}
  }
};
```

Create `frontend/src/styles.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f8fafc;
  color: #0f172a;
}

body {
  margin: 0;
}

button,
input,
select,
textarea {
  font: inherit;
}

.tabular {
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 4: Create React entry**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Ashare Research Workbench</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
```

Create `frontend/src/App.tsx`:

```tsx
export function App() {
  return (
    <main className="min-h-screen bg-surface p-6 text-ink">
      <h1 className="text-2xl font-semibold">Ashare Research Workbench</h1>
      <p className="mt-2 text-sm text-slate-600">
        Research review only. This is not a trading system.
      </p>
    </main>
  );
}
```

- [ ] **Step 5: Update `.gitignore`**

Add:

```gitignore
frontend/node_modules/
frontend/dist/
frontend/.vite/
frontend/coverage/
```

- [ ] **Step 6: Install and build**

Run:

```bash
cd frontend && npm install
cd frontend && npm run build
```

Expected: `npm run build` exits 0 and creates ignored `frontend/dist/`.

- [ ] **Step 7: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/tailwind.config.ts frontend/postcss.config.js frontend/src/main.tsx frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: scaffold react workbench"
```

## Task 6: Frontend API Client And App Shell

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write frontend smoke test**

Create `frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `frontend/src/__tests__/App.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({
    ok: true,
    json: async () => ({
      research_only: true,
      not_trading_instruction: true,
      database: { db_path: "data/processed/hs300_daily.duckdb", available: true },
      ui_runner: { enabled: false },
      research_notices: ["candidate list is not a trading instruction"]
    })
  }))
);

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("App", () => {
  it("renders research workbench shell", async () => {
    renderApp();

    expect(await screen.findByText("Ashare Research Workbench")).toBeInTheDocument();
    expect(screen.getByText(/not a trading system/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Today" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing frontend test**

Run:

```bash
cd frontend && npm test
```

Expected: fail until app shell and routes are implemented.

- [ ] **Step 3: Implement API client**

Create `frontend/src/api/client.ts`:

```ts
export type UIConfig = {
  research_only: boolean;
  not_trading_instruction: boolean;
  database: {
    db_path: string;
    available: boolean;
  };
  ui_runner: {
    enabled: boolean;
    history_dir?: string;
    log_dir?: string;
    allowed_commands?: string[];
    require_confirmation?: boolean;
  };
  research_notices: string[];
};

export type ArtifactRecord = {
  artifact_id: string;
  kind: string;
  title: string;
  output_dir: string;
  updated_at: string;
};

export type UIRunRecord = {
  ui_run_id: string;
  task_type: string;
  status: "queued" | "running" | "success" | "failed" | "cancelled";
  params: Record<string, unknown>;
  command_preview: string[];
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  steps: Array<Record<string, unknown>>;
  log_paths: string[];
  artifact_paths: string[];
  error_code?: string | null;
  error_message?: string | null;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  uiConfig: () => getJson<UIConfig>("/api/v1/ui/config"),
  artifacts: () => getJson<{ artifacts: ArtifactRecord[] }>("/api/v1/artifacts?limit=100"),
  uiRuns: () => getJson<{ runs: UIRunRecord[] }>("/api/v1/ui/runs"),
  createStockReportRun: (body: unknown) =>
    postJson<{ run: UIRunRecord }>("/api/v1/ui/runs/stock-report", body),
  createHs300DailyRun: (body: unknown) =>
    postJson<{ run: UIRunRecord }>("/api/v1/ui/runs/hs300-daily", body),
  executeRun: (uiRunId: string) =>
    postJson<{ run: UIRunRecord }>(`/api/v1/ui/runs/${uiRunId}/execute`, {})
};
```

- [ ] **Step 4: Implement shell components**

Create `frontend/src/components/StatusBadge.tsx`:

```tsx
type StatusBadgeProps = {
  status: string;
};

const styles: Record<string, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  running: "border-blue-200 bg-blue-50 text-blue-700",
  failed: "border-red-200 bg-red-50 text-red-700",
  queued: "border-slate-200 bg-slate-50 text-slate-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700"
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`inline-flex rounded border px-2 py-1 text-xs font-medium ${styles[status] ?? styles.queued}`}>
      {status}
    </span>
  );
}
```

Create `frontend/src/components/AppShell.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { StatusBadge } from "./StatusBadge";

const navItems = [
  ["Today", "/"],
  ["Stocks", "/stocks"],
  ["Reports", "/reports"],
  ["Runs", "/runs"],
  ["Artifacts", "/artifacts"],
  ["Settings", "/settings"]
] as const;

export function AppShell() {
  const config = useQuery({ queryKey: ["ui-config"], queryFn: api.uiConfig });
  const dbAvailable = config.data?.database.available;

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-950">
      <aside className="w-64 border-r border-slate-200 bg-white p-4">
        <h1 className="text-lg font-semibold">Ashare Research Workbench</h1>
        <p className="mt-1 text-xs text-slate-500">Local research review only</p>
        <nav className="mt-6 space-y-1">
          {navItems.map(([label, path]) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
          <div className="text-sm text-slate-600">
            {config.data?.database.db_path ?? "Loading database config..."}
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={dbAvailable ? "success" : "warning"} />
            <span className="text-xs text-slate-500">not a trading system</span>
          </div>
        </header>
        <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-900">
          Research outputs are for review only. Candidate lists and composite scores are not trading instructions.
        </div>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire routes in `App.tsx`**

Replace `frontend/src/App.tsx` with:

```tsx
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";

function WorkbenchIntro({ title }: { title: string }) {
  return (
    <section>
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-slate-600">This page is part of the local research workbench.</p>
    </section>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<WorkbenchIntro title="Today" />} />
        <Route path="/stocks" element={<WorkbenchIntro title="Stocks" />} />
        <Route path="/reports" element={<WorkbenchIntro title="Reports" />} />
        <Route path="/runs" element={<WorkbenchIntro title="Runs" />} />
        <Route path="/artifacts" element={<WorkbenchIntro title="Artifacts" />} />
        <Route path="/settings" element={<WorkbenchIntro title="Settings" />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 6: Run frontend test and build**

Run:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: add research workbench shell"
```

## Task 7: Read-Only Frontend Pages

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/components/ArtifactTable.tsx`
- Create: `frontend/src/components/ReportViewer.tsx`
- Create: `frontend/src/pages/TodayPage.tsx`
- Create: `frontend/src/pages/ReportsPage.tsx`
- Create: `frontend/src/pages/ArtifactsPage.tsx`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Extend API client for latest reports and markdown**

Add to `frontend/src/api/client.ts`:

```ts
export type CsvPayload = {
  artifact_id: string;
  rows: Array<Record<string, unknown>>;
};

export const reportApi = {
  latestDaily: () => getJson<CsvPayload>("/api/v1/reports/daily/latest"),
  latestScoring: () => getJson<CsvPayload>("/api/v1/scoring/latest"),
  markdown: async (artifactId: string) => {
    const response = await fetch(`/api/v1/reports/${artifactId}/markdown`);
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.text();
  }
};
```

- [ ] **Step 2: Create artifact table**

Create `frontend/src/components/ArtifactTable.tsx`:

```tsx
import type { ArtifactRecord } from "../api/client";

type ArtifactTableProps = {
  artifacts: ArtifactRecord[];
};

export function ArtifactTable({ artifacts }: ArtifactTableProps) {
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">Kind</th>
            <th className="px-3 py-2">Title</th>
            <th className="px-3 py-2">Updated</th>
            <th className="px-3 py-2">Path</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {artifacts.map((artifact) => (
            <tr key={artifact.artifact_id}>
              <td className="px-3 py-2 font-medium">{artifact.kind}</td>
              <td className="px-3 py-2">{artifact.title}</td>
              <td className="px-3 py-2 tabular text-slate-600">{artifact.updated_at}</td>
              <td className="px-3 py-2">
                <code className="break-all text-xs text-slate-600">{artifact.output_dir}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Create report viewer**

Create `frontend/src/components/ReportViewer.tsx`:

```tsx
import ReactMarkdown from "react-markdown";

type ReportViewerProps = {
  markdown?: string;
  isLoading?: boolean;
};

export function ReportViewer({ markdown, isLoading }: ReportViewerProps) {
  if (isLoading) {
    return <div className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">Loading report...</div>;
  }
  if (!markdown) {
    return <div className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">No report selected.</div>;
  }
  return (
    <article className="prose max-w-none rounded border border-slate-200 bg-white p-5">
      <ReactMarkdown>{markdown}</ReactMarkdown>
    </article>
  );
}
```

- [ ] **Step 4: Create Today page**

Create `frontend/src/pages/TodayPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api, reportApi } from "../api/client";
import { ArtifactTable } from "../components/ArtifactTable";
import { StatusBadge } from "../components/StatusBadge";

export function TodayPage() {
  const config = useQuery({ queryKey: ["ui-config"], queryFn: api.uiConfig });
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: api.artifacts });
  const scoring = useQuery({ queryKey: ["latest-scoring"], queryFn: reportApi.latestScoring });

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Today</h2>
        <p className="mt-1 text-sm text-slate-600">Daily research review snapshot.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded border border-slate-200 bg-white p-4">
          <div className="text-sm text-slate-500">Database</div>
          <div className="mt-2 break-all text-sm font-medium">{config.data?.database.db_path ?? "Loading..."}</div>
        </div>
        <div className="rounded border border-slate-200 bg-white p-4">
          <div className="text-sm text-slate-500">DB status</div>
          <div className="mt-2"><StatusBadge status={config.data?.database.available ? "success" : "warning"} /></div>
        </div>
        <div className="rounded border border-slate-200 bg-white p-4">
          <div className="text-sm text-slate-500">Latest scored rows</div>
          <div className="mt-2 text-2xl font-semibold">{scoring.data?.rows.length ?? 0}</div>
        </div>
      </div>
      <ArtifactTable artifacts={artifacts.data?.artifacts.slice(0, 10) ?? []} />
    </section>
  );
}
```

- [ ] **Step 5: Create Artifacts and Settings pages**

Create `frontend/src/pages/ArtifactsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ArtifactTable } from "../components/ArtifactTable";

export function ArtifactsPage() {
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: api.artifacts });
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Artifacts</h2>
      <ArtifactTable artifacts={artifacts.data?.artifacts ?? []} />
    </section>
  );
}
```

Create `frontend/src/pages/SettingsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function SettingsPage() {
  const config = useQuery({ queryKey: ["ui-config"], queryFn: api.uiConfig });
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">Settings</h2>
      <div className="rounded border border-slate-200 bg-white p-4 text-sm">
        <dl className="grid gap-3">
          <div>
            <dt className="text-slate-500">API</dt>
            <dd>{config.data?.api_base_url ?? "http://127.0.0.1:8008"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">UI runner</dt>
            <dd>{config.data?.ui_runner.enabled ? "enabled" : "disabled"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Research notices</dt>
            <dd>{config.data?.research_notices.join(" · ")}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Create Reports page**

Create `frontend/src/pages/ReportsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api, reportApi } from "../api/client";
import { ReportViewer } from "../components/ReportViewer";

export function ReportsPage() {
  const artifacts = useQuery({ queryKey: ["artifacts"], queryFn: api.artifacts });
  const firstReport = artifacts.data?.artifacts.find((artifact) =>
    ["daily_report", "stock_report", "factor_validation", "scoring", "backtest"].includes(artifact.kind)
  );
  const markdown = useQuery({
    queryKey: ["markdown", firstReport?.artifact_id],
    queryFn: () => reportApi.markdown(firstReport!.artifact_id),
    enabled: Boolean(firstReport)
  });

  return (
    <section className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <aside className="rounded border border-slate-200 bg-white p-4">
        <h2 className="text-lg font-semibold">Reports</h2>
        <div className="mt-3 space-y-2">
          {(artifacts.data?.artifacts ?? []).map((artifact) => (
            <div key={artifact.artifact_id} className="rounded border border-slate-100 p-2 text-sm">
              <div className="font-medium">{artifact.title}</div>
              <div className="text-xs text-slate-500">{artifact.kind}</div>
            </div>
          ))}
        </div>
      </aside>
      <ReportViewer markdown={markdown.data} isLoading={markdown.isLoading} />
    </section>
  );
}
```

- [ ] **Step 7: Wire pages in `App.tsx`**

Replace the interim page components in `frontend/src/App.tsx` imports and routes:

```tsx
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ArtifactsPage } from "./pages/ArtifactsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";

function WorkbenchIntro({ title }: { title: string }) {
  return (
    <section>
      <h2 className="text-xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-slate-600">This page is part of the local research workbench.</p>
    </section>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TodayPage />} />
        <Route path="/stocks" element={<WorkbenchIntro title="Stocks" />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/runs" element={<WorkbenchIntro title="Runs" />} />
        <Route path="/artifacts" element={<ArtifactsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 8: Run frontend validation**

Run:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Expected: both pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat: add read-only research pages"
```

## Task 8: Runs And Stocks Frontend Pages

**Files:**
- Create: `frontend/src/api/logStream.ts`
- Create: `frontend/src/components/CommandPreview.tsx`
- Create: `frontend/src/components/RunTimeline.tsx`
- Create: `frontend/src/components/LogStream.tsx`
- Create: `frontend/src/pages/RunsPage.tsx`
- Create: `frontend/src/pages/StocksPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create log stream helper**

Create `frontend/src/api/logStream.ts`:

```ts
export type LogEvent = {
  type: "log" | "status";
  message?: string;
  status?: string;
};

export function openLogStream(uiRunId: string, onEvent: (event: LogEvent) => void): EventSource {
  const source = new EventSource(`/api/v1/ui/runs/${uiRunId}/logs/stream`);
  source.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as LogEvent);
  };
  return source;
}
```

- [ ] **Step 2: Create run UI components**

Create `frontend/src/components/CommandPreview.tsx`:

```tsx
type CommandPreviewProps = {
  command: string[];
};

export function CommandPreview({ command }: CommandPreviewProps) {
  return (
    <pre className="overflow-auto rounded border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">
      {command.map((part) => (part.includes(" ") ? JSON.stringify(part) : part)).join(" ")}
    </pre>
  );
}
```

Create `frontend/src/components/RunTimeline.tsx`:

```tsx
import { StatusBadge } from "./StatusBadge";

type RunTimelineProps = {
  steps: Array<Record<string, unknown>>;
};

export function RunTimeline({ steps }: RunTimelineProps) {
  if (!steps.length) {
    return <p className="text-sm text-slate-500">No steps recorded yet.</p>;
  }
  return (
    <ol className="space-y-2">
      {steps.map((step, index) => (
        <li key={`${step.name}-${index}`} className="rounded border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between">
            <span className="font-medium">{String(step.name ?? `step-${index + 1}`)}</span>
            <StatusBadge status={String(step.status ?? "queued")} />
          </div>
        </li>
      ))}
    </ol>
  );
}
```

Create `frontend/src/components/LogStream.tsx`:

```tsx
type LogStreamProps = {
  lines: string[];
};

export function LogStream({ lines }: LogStreamProps) {
  return (
    <pre className="h-96 overflow-auto rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-5 text-slate-100">
      {lines.length ? lines.join("\n") : "No log lines yet."}
    </pre>
  );
}
```

- [ ] **Step 3: Create Runs page**

Create `frontend/src/pages/RunsPage.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, UIRunRecord } from "../api/client";
import { openLogStream } from "../api/logStream";
import { CommandPreview } from "../components/CommandPreview";
import { LogStream } from "../components/LogStream";
import { RunTimeline } from "../components/RunTimeline";
import { StatusBadge } from "../components/StatusBadge";

export function RunsPage() {
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ["ui-runs"], queryFn: api.uiRuns });
  const [selected, setSelected] = useState<UIRunRecord | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const execute = useMutation({
    mutationFn: (uiRunId: string) => api.executeRun(uiRunId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ui-runs"] })
  });

  function stream(run: UIRunRecord) {
    setSelected(run);
    setLogLines([]);
    const source = openLogStream(run.ui_run_id, (event) => {
      if (event.type === "log" && event.message) {
        setLogLines((lines) => [...lines, event.message!]);
      }
      if (event.type === "status") {
        source.close();
      }
    });
  }

  return (
    <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <aside className="space-y-2">
        <h2 className="text-xl font-semibold">Runs</h2>
        {(runs.data?.runs ?? []).map((run) => (
          <button
            key={run.ui_run_id}
            onClick={() => setSelected(run)}
            className="block w-full rounded border border-slate-200 bg-white p-3 text-left text-sm"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{run.task_type}</span>
              <StatusBadge status={run.status} />
            </div>
            <div className="mt-1 text-xs text-slate-500">{run.ui_run_id}</div>
          </button>
        ))}
      </aside>
      <div className="space-y-4">
        {selected ? (
          <>
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">{selected.ui_run_id}</h3>
              <div className="flex gap-2">
                <button className="rounded bg-slate-900 px-3 py-2 text-sm text-white" onClick={() => execute.mutate(selected.ui_run_id)}>
                  Execute
                </button>
                <button className="rounded border border-slate-300 px-3 py-2 text-sm" onClick={() => stream(selected)}>
                  Stream logs
                </button>
              </div>
            </div>
            <CommandPreview command={selected.command_preview} />
            <RunTimeline steps={selected.steps} />
            <LogStream lines={logLines} />
          </>
        ) : (
          <div className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">Select a run.</div>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Create Stocks page with stock-report form**

Create `frontend/src/pages/StocksPage.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api } from "../api/client";

export function StocksPage() {
  const queryClient = useQueryClient();
  const [stockCode, setStockCode] = useState("002594.SZ");
  const [asOf, setAsOf] = useState("2026-05-22");
  const [sourceRunId, setSourceRunId] = useState("hs300-factor-20260522");
  const [scoreRunId, setScoreRunId] = useState("hs300-score-20260522");
  const [scanRunId, setScanRunId] = useState("hs300-scan-20260522");
  const createRun = useMutation({
    mutationFn: () =>
      api.createStockReportRun({
        stock_code: stockCode,
        as_of: asOf,
        source_run_id: sourceRunId,
        score_run_id: scoreRunId,
        scan_run_id: scanRunId,
        db_path: "data/processed/hs300_daily.duckdb",
        output_dir: `data/reports/generated/ui/stock-${stockCode.replace(".", "-")}-${asOf.replaceAll("-", "")}`,
        run_id: `ui-stock-${stockCode.replace(".", "-")}-${asOf.replaceAll("-", "")}`,
        confirmed: true
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ui-runs"] })
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    createRun.mutate();
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Stocks</h2>
        <p className="mt-1 text-sm text-slate-600">Generate a research review packet for one stock.</p>
      </div>
      <form onSubmit={submit} className="grid max-w-3xl gap-4 rounded border border-slate-200 bg-white p-4 md:grid-cols-2">
        <label className="text-sm">
          Stock code
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={stockCode} onChange={(event) => setStockCode(event.target.value)} />
        </label>
        <label className="text-sm">
          As-of
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <label className="text-sm">
          Source run id
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={sourceRunId} onChange={(event) => setSourceRunId(event.target.value)} />
        </label>
        <label className="text-sm">
          Score run id
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={scoreRunId} onChange={(event) => setScoreRunId(event.target.value)} />
        </label>
        <label className="text-sm md:col-span-2">
          Scan run id
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={scanRunId} onChange={(event) => setScanRunId(event.target.value)} />
        </label>
        <div className="md:col-span-2">
          <button className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white" type="submit">
            Generate Stock Report Run
          </button>
        </div>
      </form>
      {createRun.data ? <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">Created run {createRun.data.run.ui_run_id}. Open Runs to execute and stream logs.</div> : null}
      {createRun.error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{String(createRun.error.message)}</div> : null}
    </section>
  );
}
```

- [ ] **Step 5: Wire pages**

Update `frontend/src/App.tsx` imports and routes:

```tsx
import { RunsPage } from "./pages/RunsPage";
import { StocksPage } from "./pages/StocksPage";
```

Replace the interim routes:

```tsx
<Route path="/stocks" element={<StocksPage />} />
<Route path="/runs" element={<RunsPage />} />
```

- [ ] **Step 6: Run frontend validation**

Run:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: add ui run and stock pages"
```

## Task 9: HS300 Daily Run Form

**Files:**
- Create: `frontend/src/components/Hs300DailyRunForm.tsx`
- Modify: `frontend/src/pages/TodayPage.tsx`

- [ ] **Step 1: Create HS300 daily form component**

Create `frontend/src/components/Hs300DailyRunForm.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api } from "../api/client";

export function Hs300DailyRunForm() {
  const queryClient = useQueryClient();
  const [asOf, setAsOf] = useState("2026-05-22");
  const [stockCode, setStockCode] = useState("002594.SZ");
  const [cacheMode, setCacheMode] = useState("use");
  const [maxSymbols, setMaxSymbols] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const createRun = useMutation({
    mutationFn: () =>
      api.createHs300DailyRun({
        as_of: asOf,
        stock_code: stockCode,
        cache_mode: cacheMode,
        max_symbols: maxSymbols ? Number(maxSymbols) : null,
        confirmed
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ui-runs"] })
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    createRun.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded border border-slate-200 bg-white p-4">
      <div>
        <h3 className="font-semibold">Run HS300 Daily Workflow</h3>
        <p className="mt-1 text-sm text-slate-600">Advanced local workflow execution. This may call AkShare and write research artifacts.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm">
          As-of
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <label className="text-sm">
          Stock code
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={stockCode} onChange={(event) => setStockCode(event.target.value)} />
        </label>
        <label className="text-sm">
          Cache mode
          <select className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={cacheMode} onChange={(event) => setCacheMode(event.target.value)}>
            <option value="use">use</option>
            <option value="refresh">refresh</option>
            <option value="offline">offline</option>
          </select>
        </label>
        <label className="text-sm">
          Max symbols
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" value={maxSymbols} onChange={(event) => setMaxSymbols(event.target.value)} aria-label="Max symbols, leave empty for full run" />
        </label>
      </div>
      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input className="mt-1" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        <span>
          I understand this generates research artifacts only. Candidate lists, scores, and stock reports are not trading instructions. AkShare HS300 members are a current snapshot, not strict historical PIT.
        </span>
      </label>
      <button className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" type="submit" disabled={!confirmed}>
        Create HS300 Daily Run
      </button>
      {createRun.data ? <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">Created run {createRun.data.run.ui_run_id}. Open Runs to execute and stream logs.</div> : null}
      {createRun.error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{String(createRun.error.message)}</div> : null}
    </form>
  );
}
```

- [ ] **Step 2: Add form to Today page**

In `frontend/src/pages/TodayPage.tsx`, import:

```tsx
import { Hs300DailyRunForm } from "../components/Hs300DailyRunForm";
```

Render below the summary cards:

```tsx
<Hs300DailyRunForm />
```

- [ ] **Step 3: Run frontend validation**

Run:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Expected: both pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat: add hs300 daily run form"
```

## Task 10: Documentation And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` if frontend generated files reveal additional ignored paths.

- [ ] **Step 1: Update README**

Add a section after "常用 CLI":

```markdown
## 本地网页 UI

第一版网页 UI 使用双服务：

```bash
conda run -n ashare-research-lab ashare serve --service-config configs/service.yaml
cd frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

FastAPI 默认监听 `127.0.0.1:8008`，Vite 会把 `/api` 请求代理到 FastAPI。

默认配置下，网页只做只读查询和研究复盘；如果要从网页触发 workflow，需要在本地配置中显式启用 `ui_runner.enabled`，并保持本机访问边界。网页触发的任务历史写入 `data/service/workflow-runs/`，日志写入 `data/service/workflow-logs/`，这些目录不提交到 Git。

网页输出仍然遵守研究边界：

- candidate list is not a trading instruction
- composite score is not a trading instruction
- backtest is a historical simulation, not a performance promise
- stock report is for research review only
```
```

- [ ] **Step 2: Run backend verification**

Run:

```bash
conda run -n ashare-research-lab python -m compileall -q src/ashare tests
conda run -n ashare-research-lab ruff check .
conda run -n ashare-research-lab pytest -q tests/test_service_config.py tests/test_service_ui_runs.py tests/test_service_api.py
```

Expected: all commands exit 0.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd frontend && npm test
cd frontend && npm run build
```

Expected: all commands exit 0.

- [ ] **Step 4: Run full test suite**

Run:

```bash
conda run -n ashare-research-lab pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: document local ui workbench"
```

## Final Manual Smoke

- [ ] **Step 1: Start backend**

Run:

```bash
conda run -n ashare-research-lab ashare serve --service-config configs/service.yaml
```

Expected: FastAPI starts on `127.0.0.1:8008`.

- [ ] **Step 2: Start frontend**

Run:

```bash
cd frontend && npm run dev
```

Expected: Vite starts on `127.0.0.1:5173`.

- [ ] **Step 3: Open UI**

Open:

```text
http://127.0.0.1:5173
```

Expected:

- Sidebar shows `Today`, `Stocks`, `Reports`, `Runs`, `Artifacts`, `Settings`.
- Research-only banner is visible.
- Settings shows UI runner disabled by default.
- Artifacts page loads or shows an empty state without crashing.

- [ ] **Step 4: Verify no generated data is staged**

Run:

```bash
git status --short
```

Expected: no `data/`, `frontend/node_modules/`, `frontend/dist/`, or `.superpowers/` files are staged.

## Self-Review Checklist

- Spec coverage: backend runner, task history, logs, six pages, two-service frontend, safe local defaults, and research-only notices are covered by tasks.
- The plan contains concrete file paths, commands, DTO names, and route names.
- Type names used across backend tasks are consistent: `UIRunRecord`, `UIRunStatus`, `StockReportRunRequest`, `Hs300DailyRunRequest`.
- Frontend endpoint names match backend routes under `/api/v1/ui/*`.
- Mutating workflows remain disabled by default and require explicit confirmation.
- The plan avoids buy/sell/target/position language.
