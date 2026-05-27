from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ashare.service.config import load_service_config
from ashare.service.ui_runs import (
    Hs300DailyRunRequest,
    StockReportRunRequest,
    UIRunRecord,
    UIRunStatus,
    build_hs300_daily_command,
    build_stock_report_command,
    create_ui_run,
    list_ui_runs,
    read_ui_run,
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
