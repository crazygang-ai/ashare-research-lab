"""Local UI-triggered research task history and command previews."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ashare.service.config import ServiceConfig
from ashare.service.schemas import jsonable


_UI_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_STOCK_CODE_PATTERN = r"^\d{6}\.(SH|SZ)$"


def _strip_non_empty(value: str, *, field_kind: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_kind} must be non-empty.")
    return stripped


def _strip_optional_non_empty(value: str | None, *, field_kind: str) -> str | None:
    if value is None:
        return None
    return _strip_non_empty(value, field_kind=field_kind)


class UIRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StockReportRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=_STOCK_CODE_PATTERN)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_run_id: str = Field(min_length=1)
    score_run_id: str = Field(min_length=1)
    scan_run_id: str | None = None
    db_path: str = Field(default="data/processed/hs300_daily.duckdb", min_length=1)
    output_dir: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    confirmed: bool = False

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("source_run_id", "score_run_id", "run_id")
    @classmethod
    def strip_non_empty_identifier(cls, value: str) -> str:
        return _strip_non_empty(value, field_kind="identifier field")

    @field_validator("scan_run_id")
    @classmethod
    def strip_optional_identifier(cls, value: str | None) -> str | None:
        return _strip_optional_non_empty(value, field_kind="identifier field")

    @field_validator("db_path", "output_dir")
    @classmethod
    def strip_non_empty_path(cls, value: str) -> str:
        return _strip_non_empty(value, field_kind="path field")

    @model_validator(mode="after")
    def require_confirmation(self) -> "StockReportRunRequest":
        if not self.confirmed:
            raise ValueError("confirmed must be true for stock-report runs.")
        return self


class Hs300DailyRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    stock_code: str = Field(default="002594.SZ", pattern=_STOCK_CODE_PATTERN)
    cache_mode: str = "use"
    max_symbols: int | None = Field(default=None, gt=0)
    watchlist_file: str | None = None
    confirmed: bool = False

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("watchlist_file")
    @classmethod
    def strip_optional_path(cls, value: str | None) -> str | None:
        return _strip_optional_non_empty(value, field_kind="path field")

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


def build_stock_report_command(
    config: ServiceConfig,
    request: StockReportRunRequest,
) -> list[str]:
    del config
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


def build_hs300_daily_command(
    config: ServiceConfig,
    request: Hs300DailyRunRequest,
) -> list[str]:
    del config
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


def create_ui_run(
    config: ServiceConfig,
    *,
    task_type: str,
    params: dict[str, Any],
) -> UIRunRecord:
    if task_type not in config.ui_runner_allowed_commands:
        raise ValueError(f"Unsupported UI task type: {task_type}")

    if task_type == "stock-report":
        stock_request = StockReportRunRequest(**params)
        command = build_stock_report_command(config, stock_request)
        run_params = stock_request.model_dump()
    elif task_type == "hs300-daily":
        hs300_request = Hs300DailyRunRequest(**params)
        command = build_hs300_daily_command(config, hs300_request)
        run_params = hs300_request.model_dump()
    else:
        raise ValueError(f"Unsupported UI task type: {task_type}")

    run = UIRunRecord(
        ui_run_id=_new_ui_run_id(task_type),
        task_type=task_type,
        status=UIRunStatus.QUEUED,
        params=run_params,
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
    if not _UI_RUN_ID_RE.fullmatch(ui_run_id):
        return None
    history_dir = config.ui_runner_history_dir.resolve()
    path = (history_dir / f"{ui_run_id}.json").resolve()
    if not path.is_relative_to(history_dir):
        return None
    if not path.is_file():
        return None
    try:
        record = _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
        _created_at_sort_key(record.created_at)
        return record
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def list_ui_runs(config: ServiceConfig, limit: int = 50) -> list[UIRunRecord]:
    if not config.ui_runner_history_dir.is_dir():
        return []
    records: list[tuple[datetime, UIRunRecord]] = []
    for path in config.ui_runner_history_dir.glob("*.json"):
        try:
            record = _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
            records.append((_created_at_sort_key(record.created_at), record))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue
    records.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in records[:limit]]


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
    return f"{safe_type}-{timestamp}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _created_at_sort_key(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
