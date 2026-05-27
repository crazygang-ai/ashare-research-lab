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
