from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from ashare.service.app import create_app
from ashare.service.ui_runs import UIRunRecord, UIRunStatus, write_ui_run
from ashare.storage.db import init_db


def test_service_api_reads_artifacts_and_duckdb_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    db_path = tmp_path / "ashare.duckdb"
    _write_artifacts(root)
    _write_factor_db(db_path)
    before = _factor_count(db_path)
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(db_path), "read_only": True},
            "artifacts": {"roots": [str(root)]},
        },
    )
    client = TestClient(app)

    for path in ["/health", "/api/v1/status", "/api/v1/artifacts", "/"]:
        response = client.get(path)
        assert response.status_code == 200, response.text

    status = client.get("/api/v1/status").json()
    assert status["database"]["available"] is True
    assert status["database"]["db_path"].endswith("ashare.duckdb")
    assert status["workflows"]["target_db_paths"]["phase4-fixture-research"]

    assert client.get("/api/v1/artifacts", params={"kind": "scan", "limit": 20}).status_code == 200
    scan_latest = client.get("/api/v1/scans/latest")
    assert scan_latest.status_code == 200
    assert scan_latest.json()["rows"][0]["stock_code"] == "000001.SZ"
    assert client.get("/api/v1/scoring/latest").status_code == 200
    assert client.get("/api/v1/backtests/latest").status_code == 200
    assert client.get("/api/v1/reports/daily/latest").status_code == 200
    assert client.get("/api/v1/reports/stocks/latest").status_code == 200
    daily_markdown = client.get("/api/v1/reports/daily/latest/markdown")
    stock_markdown = client.get("/api/v1/reports/stocks/latest/markdown")
    assert daily_markdown.status_code == 200
    assert stock_markdown.status_code == 200
    assert "Daily Research Report" in daily_markdown.text
    assert "Stock Research Report" in stock_markdown.text
    validation = client.get("/api/v1/factors/return_20d/validation")
    assert validation.status_code == 200
    assert validation.json()["ic_summary"][0]["factor_name"] == "return_20d"

    factors = client.get(
        "/api/v1/stocks/000001.SZ/factors",
        params={"as_of": "2026-06-26", "source_run_id": "phase4-service"},
    )
    assert factors.status_code == 200
    payload = factors.json()
    assert payload["research_only"] is True
    assert payload["not_trading_instruction"] is True
    assert payload["rows"][0]["factor_name"] == "return_20d"
    assert _factor_count(db_path) == before

    artifact_id = scan_latest.json()["artifact_id"]
    markdown = client.get(f"/api/v1/reports/{artifact_id}/markdown")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "<h1>" not in markdown.text
    assert "Candidate List" in markdown.text

    html = client.get("/").text
    assert "研究复盘" in html
    assert "不是交易指令" in html
    assert "<script" not in html.lower()
    assert "&lt;unsafe&gt;" in html

    blocked = client.post("/api/v1/workflows/phase4-fixture-research/run")
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "workflow_http_disabled"


def test_service_status_handles_missing_database(tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(tmp_path / "missing.duckdb"), "read_only": True},
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    client = TestClient(app)

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["database"]["available"] is False


def test_workflow_api_token_order_and_header(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASHARE_SERVICE_TOKEN", "secret")
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "security": {"allow_http_workflow_run": True},
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    client = TestClient(app)

    missing = client.post("/api/v1/workflows/phase4-fixture-research/run")
    wrong = client.post(
        "/api/v1/workflows/phase4-fixture-research/run",
        headers={"X-Ashare-Token": "wrong"},
    )
    ok_auth_disabled_workflow = client.post(
        "/api/v1/workflows/phase4-fixture-research/run",
        headers={"X-Ashare-Token": "secret"},
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "missing_or_invalid_token"
    assert wrong.status_code == 401
    assert ok_auth_disabled_workflow.status_code == 409
    assert ok_auth_disabled_workflow.json()["error_code"] == "workflow_disabled"


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


def test_ui_run_history_endpoint_lists_created_run(tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "ui_runner": {
                "enabled": True,
                "history_dir": str(tmp_path / "runs"),
                "log_dir": "data/service/test-api-ui-logs/history",
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
    run = created.json()["run"]
    assert run["status"] == "queued"
    runs = client.get("/api/v1/ui/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["ui_run_id"] == run["ui_run_id"]
    assert runs.json()["runs"][0]["task_type"] == "hs300-daily"
    detail = client.get(f"/api/v1/ui/runs/{run['ui_run_id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["ui_run_id"] == run["ui_run_id"]


def test_ui_run_execute_endpoint_calls_execute_ui_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "ui_runner": {
                "enabled": True,
                "history_dir": str(tmp_path / "runs"),
                "log_dir": "data/service/test-api-ui-logs/execute",
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
    ui_run_id = created.json()["run"]["ui_run_id"]
    calls: list[str] = []

    def fake_execute_ui_run(config, requested_ui_run_id: str) -> UIRunRecord:
        calls.append(requested_ui_run_id)
        return UIRunRecord(
            ui_run_id=requested_ui_run_id,
            task_type="hs300-daily",
            status=UIRunStatus.SUCCESS,
            params={"as_of": "2026-05-22"},
            command_preview=["fake"],
            created_at="2026-05-22T00:00:00+00:00",
        )

    monkeypatch.setattr("ashare.service.app.execute_ui_run", fake_execute_ui_run)

    response = client.post(f"/api/v1/ui/runs/{ui_run_id}/execute")

    assert response.status_code == 200
    assert calls == [ui_run_id]
    assert response.json()["run"]["status"] == "success"


def test_ui_run_log_stream_returns_sse_events(tmp_path: Path) -> None:
    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "ui_runner": {
                "enabled": True,
                "history_dir": str(tmp_path / "runs"),
                "log_dir": "data/service/test-api-ui-logs/stream",
            },
            "artifacts": {"roots": [str(tmp_path / "reports")]},
        },
    )
    config = app.state.service_config
    log_dir = config.ui_runner_log_dir / "ui-run-with-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "main.log"
    log_path.write_text("first log line\n", encoding="utf-8")
    write_ui_run(
        config,
        UIRunRecord(
            ui_run_id="ui-run-with-log",
            task_type="hs300-daily",
            status=UIRunStatus.SUCCESS,
            params={"as_of": "2026-05-22"},
            command_preview=["fake"],
            created_at="2026-05-22T00:00:00+00:00",
            log_paths=[config.repo_relative(log_path)],
        ),
    )
    client = TestClient(app)

    response = client.get("/api/v1/ui/runs/ui-run-with-log/logs/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "log", "message": "first log line"}' in response.text
    assert 'data: {"type": "status", "status": "success"}' in response.text


def _write_artifacts(root: Path) -> None:
    scan = root / "scan"
    scan.mkdir(parents=True)
    (scan / "candidate_list.md").write_text("# Candidate List\n候选\n", encoding="utf-8")
    (scan / "candidates.csv").write_text(
        "rank,stock_code,selection_reason\n1,000001.SZ,return_20d\n",
        encoding="utf-8",
    )
    scoring = root / "scoring"
    scoring.mkdir()
    (scoring / "scoring_report.md").write_text("# Scoring\n", encoding="utf-8")
    (scoring / "scored_candidates.csv").write_text(
        "rank,stock_code,total_score\n1,000001.SZ,88\n",
        encoding="utf-8",
    )
    (scoring / "score_metadata.json").write_text(
        '{"generated_at":"2026-06-26T18:00:00+08:00","title":"Score <unsafe>"}\n',
        encoding="utf-8",
    )
    backtest = root / "backtest"
    backtest.mkdir()
    (backtest / "backtest_report.md").write_text("# Backtest\n", encoding="utf-8")
    (backtest / "metrics.csv").write_text("total_return,max_drawdown\n0.1,-0.2\n", encoding="utf-8")
    (backtest / "equity_curve.csv").write_text("trade_date,nav\n2026-06-26,1.0\n", encoding="utf-8")
    validation = root / "factor-validation"
    validation.mkdir()
    (validation / "factor_validation_report.md").write_text("# Validation\n", encoding="utf-8")
    (validation / "coverage.csv").write_text("factor_name,coverage\nreturn_20d,1\n", encoding="utf-8")
    (validation / "rank_ic.csv").write_text("factor_name,horizon,rank_ic\nreturn_20d,20,0.1\n", encoding="utf-8")
    (validation / "ic_summary.csv").write_text("factor_name,horizon,icir\nreturn_20d,20,1.2\n", encoding="utf-8")
    daily = root / "daily-report"
    daily.mkdir()
    (daily / "daily_report.md").write_text("# Daily Research Report\n", encoding="utf-8")
    (daily / "daily_candidates.csv").write_text(
        "rank,stock_code\n1,000001.SZ\n",
        encoding="utf-8",
    )
    (daily / "daily_score_summary.csv").write_text(
        "rank,stock_code,total_score\n1,000001.SZ,88\n",
        encoding="utf-8",
    )
    (daily / "daily_metadata.json").write_text(
        '{"generated_at":"2026-06-26T19:00:00+08:00","title":"Daily"}\n',
        encoding="utf-8",
    )
    stock = root / "stock-report"
    stock.mkdir()
    (stock / "stock_report.md").write_text("# Stock Research Report\n", encoding="utf-8")
    (stock / "stock_factor_values.csv").write_text(
        "stock_code,factor_name,factor_value\n000001.SZ,return_20d,0.25\n",
        encoding="utf-8",
    )
    (stock / "stock_score_breakdown.csv").write_text(
        "detail_type,score_group,factor_name\nfactor,momentum,return_20d\n",
        encoding="utf-8",
    )
    (stock / "stock_metadata.json").write_text(
        '{"generated_at":"2026-06-26T19:30:00+08:00","title":"Stock"}\n',
        encoding="utf-8",
    )


def _write_factor_db(db_path: Path) -> None:
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ["000001.SZ", date(2026, 6, 26), "return_20d", 0.25, date(2026, 6, 26), "phase4-service"],
        )
    finally:
        connection.close()


def _factor_count(db_path: Path) -> int:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0])
    finally:
        connection.close()
