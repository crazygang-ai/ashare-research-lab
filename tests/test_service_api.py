from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from ashare.service.app import create_app
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
