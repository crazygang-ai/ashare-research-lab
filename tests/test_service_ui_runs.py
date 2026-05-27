from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time

import pytest
from pydantic import ValidationError

from ashare.service.config import load_service_config
from ashare.service.ui_runs import (
    Hs300DailyRunRequest,
    StockReportRunRequest,
    UIRunAlreadyRunningError,
    UIRunRecord,
    UIRunStatus,
    build_hs300_daily_command,
    build_stock_report_command,
    create_ui_run,
    execute_ui_run,
    list_ui_runs,
    read_ui_run,
    stream_log_events,
    write_ui_run,
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


def test_build_stock_report_command_is_explicit_conda_invocation(
    tmp_path: Path,
) -> None:
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


def test_list_ui_runs_sorts_by_created_at_desc_across_task_types(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    write_ui_run(
        config,
        UIRunRecord(
            ui_run_id="stock-report-old",
            task_type="stock-report",
            status=UIRunStatus.QUEUED,
            params={},
            command_preview=[],
            created_at="2026-05-22T00:00:00+00:00",
        ),
    )
    write_ui_run(
        config,
        UIRunRecord(
            ui_run_id="hs300-daily-new",
            task_type="hs300-daily",
            status=UIRunStatus.QUEUED,
            params={},
            command_preview=[],
            created_at="2026-05-23T00:00:00+00:00",
        ),
    )

    runs = list_ui_runs(config, limit=1)

    assert [run.ui_run_id for run in runs] == ["hs300-daily-new"]


def test_list_ui_runs_skips_bad_json_files(tmp_path: Path) -> None:
    config = _config(tmp_path)
    valid = UIRunRecord(
        ui_run_id="hs300-daily-valid",
        task_type="hs300-daily",
        status=UIRunStatus.QUEUED,
        params={},
        command_preview=[],
        created_at="2026-05-23T00:00:00+00:00",
    )
    write_ui_run(config, valid)
    config.ui_runner_history_dir.mkdir(parents=True, exist_ok=True)
    (config.ui_runner_history_dir / "bad-json.json").write_text("{", encoding="utf-8")
    (config.ui_runner_history_dir / "bad-schema.json").write_text(
        json.dumps({"ui_run_id": "missing-fields"}),
        encoding="utf-8",
    )

    runs = list_ui_runs(config)

    assert [run.ui_run_id for run in runs] == ["hs300-daily-valid"]


def test_read_ui_run_rejects_path_traversal(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.ui_runner_history_dir.mkdir(parents=True, exist_ok=True)
    outside = UIRunRecord(
        ui_run_id="outside",
        task_type="hs300-daily",
        status=UIRunStatus.QUEUED,
        params={},
        command_preview=[],
        created_at="2026-05-23T00:00:00+00:00",
    )
    outside_path = tmp_path / "outside.json"
    outside_path.write_text(
        json.dumps(outside.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    assert read_ui_run(config, "../outside") is None


def test_request_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        StockReportRunRequest(
            stock_code="002594.SZ",
            as_of="2026-05-22",
            source_run_id="factor",
            score_run_id="score",
            output_dir="data/reports/generated/ui/stock-002594-SZ",
            run_id="stock-ui",
            confirmed=True,
            unexpected="field",
        )


@pytest.mark.parametrize(
    "field",
    ["source_run_id", "score_run_id", "run_id", "scan_run_id"],
)
def test_stock_report_request_rejects_blank_identifiers(field: str) -> None:
    params = {
        "stock_code": "002594.SZ",
        "as_of": "2026-05-22",
        "source_run_id": "factor",
        "score_run_id": "score",
        "scan_run_id": "scan",
        "output_dir": "data/reports/generated/ui/stock-002594-SZ",
        "run_id": "stock-ui",
        "confirmed": True,
    }
    params[field] = "   "

    with pytest.raises(ValidationError):
        StockReportRunRequest(**params)


def test_stock_report_request_allows_missing_scan_run_id() -> None:
    request = StockReportRunRequest(
        stock_code="002594.SZ",
        as_of="2026-05-22",
        source_run_id="factor",
        score_run_id="score",
        scan_run_id=None,
        output_dir="data/reports/generated/ui/stock-002594-SZ",
        run_id="stock-ui",
        confirmed=True,
    )

    assert request.scan_run_id is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cache_mode", "invalid"),
        ("confirmed", False),
        ("stock_code", "BADCODE"),
        ("as_of", "2026-02-31"),
    ],
)
def test_hs300_daily_request_rejects_invalid_inputs(field: str, value: object) -> None:
    params = {
        "as_of": "2026-05-22",
        "stock_code": "002594.SZ",
        "cache_mode": "use",
        "confirmed": True,
    }
    params[field] = value

    with pytest.raises(ValidationError):
        Hs300DailyRunRequest(**params)


def test_create_ui_run_generates_unique_ids_for_same_microsecond(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 22, 1, 2, 3, 123456, tzinfo=timezone.utc)

    monkeypatch.setattr("ashare.service.ui_runs.datetime", FixedDateTime)

    first = create_ui_run(
        config,
        task_type="hs300-daily",
        params={
            "as_of": "2026-05-22",
            "stock_code": "002594.SZ",
            "cache_mode": "use",
            "confirmed": True,
        },
    )
    second = create_ui_run(
        config,
        task_type="hs300-daily",
        params={
            "as_of": "2026-05-22",
            "stock_code": "002594.SZ",
            "cache_mode": "use",
            "confirmed": True,
        },
    )

    assert first.ui_run_id != second.ui_run_id


def test_execute_ui_run_writes_stdout_and_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    run = _queued_hs300_run(config)
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [
            sys.executable,
            "-c",
            "print('ui stdout line')",
        ],
    )

    result = execute_ui_run(config, run.ui_run_id)

    assert result.status == UIRunStatus.SUCCESS
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.command_preview == [
        sys.executable,
        "-c",
        "print('ui stdout line')",
    ]
    assert len(result.log_paths) == 1
    log_path = Path(result.log_paths[0])
    assert log_path.read_text(encoding="utf-8") == "ui stdout line\n"
    saved = read_ui_run(config, run.ui_run_id)
    assert saved is not None
    assert saved.status == UIRunStatus.SUCCESS


def test_execute_ui_run_marks_failed_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    run = _queued_hs300_run(config)
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [
            sys.executable,
            "-c",
            "print('failure line'); raise SystemExit(7)",
        ],
    )

    result = execute_ui_run(config, run.ui_run_id)

    assert result.status == UIRunStatus.FAILED
    assert result.error_code == "command_failed"
    assert result.error_message is not None
    assert "exit code 7" in result.error_message
    assert Path(result.log_paths[0]).read_text(encoding="utf-8") == "failure line\n"
    saved = read_ui_run(config, run.ui_run_id)
    assert saved is not None
    assert saved.status == UIRunStatus.FAILED


def test_execute_ui_run_rejects_concurrent_mutating_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first = _queued_hs300_run(config)
    second = _queued_hs300_run(config)
    monkeypatch.setattr(
        "ashare.service.ui_runs.command_for_run",
        lambda config, run: [
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(0.5)",
        ],
    )
    thread_errors: list[BaseException] = []

    def run_first() -> None:
        try:
            execute_ui_run(config, first.ui_run_id)
        except BaseException as exc:  # pragma: no cover - surfaced below
            thread_errors.append(exc)

    worker = threading.Thread(target=run_first)
    worker.start()
    try:
        _wait_for_status(config, first.ui_run_id, UIRunStatus.RUNNING)
        with pytest.raises(UIRunAlreadyRunningError):
            execute_ui_run(config, second.ui_run_id)
    finally:
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert thread_errors == []


def test_stream_log_events_reads_existing_log(tmp_path: Path) -> None:
    log_path = tmp_path / "main.log"
    log_path.write_text("first line\nsecond line\n", encoding="utf-8")

    events = stream_log_events(log_path, UIRunStatus.SUCCESS)

    assert events == [
        {"type": "log", "message": "first line"},
        {"type": "log", "message": "second line"},
        {"type": "status", "status": "success"},
    ]


def _queued_hs300_run(config) -> UIRunRecord:
    return create_ui_run(
        config,
        task_type="hs300-daily",
        params={
            "as_of": "2026-05-22",
            "stock_code": "002594.SZ",
            "cache_mode": "use",
            "confirmed": True,
        },
    )


def _wait_for_status(
    config,
    ui_run_id: str,
    expected_status: UIRunStatus,
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        run = read_ui_run(config, ui_run_id)
        if run is not None and run.status == expected_status:
            return
        time.sleep(0.01)
    pytest.fail(f"Timed out waiting for {ui_run_id} to become {expected_status.value}")


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
