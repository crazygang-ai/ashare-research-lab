from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from ashare.audit.artifacts import build_artifact_record
from ashare.audit.run_store import begin_run, complete_run, insert_artifacts
from ashare.service.app import create_app
from ashare.storage.db import init_db


def test_service_prefers_artifact_index_and_exposes_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.duckdb"
    output_dir = tmp_path / "reports" / "scan-run"
    output_dir.mkdir(parents=True)
    candidates = output_dir / "candidates.csv"
    markdown = output_dir / "candidate_list.md"
    manifest = output_dir / "run_manifest.json"
    candidates.write_text("stock_code\n000001.SZ\n", encoding="utf-8")
    markdown.write_text("# Candidate List\n", encoding="utf-8")
    manifest.write_text('{"run_id":"scan-run"}\n', encoding="utf-8")

    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    started = datetime.now(timezone.utc)
    try:
        begin_run(
            connection,
            run_id="scan-run",
            as_of_date="2026-06-26",
            params={
                "command": "scan",
                "run_mode": "exploratory",
                "source_run_id": "source",
            },
            config_hash="cfg",
            data_snapshot_id="fingerprint:1",
            git_sha="sha",
            worktree_clean=True,
            started_at=started,
            overwrite=False,
        )
        records = [
            build_artifact_record(
                repo_root=Path.cwd(),
                run_id="scan-run",
                artifact_kind="scan",
                role=role,
                path=path,
                created_at=started,
            )
            for role, path in [
                ("candidates_csv", candidates),
                ("markdown_report", markdown),
                ("manifest", manifest),
            ]
        ]
        insert_artifacts(connection, records)
        complete_run(
            connection,
            run_id="scan-run",
            status="succeeded",
            params={
                "command": "scan",
                "run_mode": "exploratory",
                "source_run_id": "source",
            },
            config_hash="cfg",
            data_snapshot_id="fingerprint:1",
            finished_at=started,
            error=None,
        )
    finally:
        connection.close()

    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(db_path), "read_only": True},
            "artifacts": {"roots": [str(tmp_path / "empty-file-scan-root")]},
        },
    )
    client = TestClient(app)

    status = client.get("/api/v1/status").json()
    assert status["audit_schema_available"] is True
    assert status["artifact_index_available"] is True
    assert status["latest_run_id"] == "scan-run"

    artifacts = client.get("/api/v1/artifacts", params={"kind": "scan"}).json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["run_id"] == "scan-run"
    assert artifacts[0]["run"]["git_sha"] == "sha"

    latest = client.get("/api/v1/scans/latest")
    assert latest.status_code == 200
    assert latest.json()["rows"][0]["stock_code"] == "000001.SZ"

    assert client.get("/api/v1/runs").json()["runs"][0]["run_id"] == "scan-run"
    assert client.get("/api/v1/runs/scan-run").json()["run"]["status"] == "succeeded"
    assert client.get("/api/v1/runs/scan-run/artifacts").json()["artifacts"]
    assert client.get("/api/v1/runs/scan-run/manifest").json()["run_id"] == "scan-run"


def test_service_fallbacks_to_file_scan_without_phase5_tables(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    scan = root / "scan"
    scan.mkdir(parents=True)
    (scan / "candidates.csv").write_text("stock_code\n000001.SZ\n", encoding="utf-8")
    (scan / "candidate_list.md").write_text("# Candidate List\n", encoding="utf-8")

    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(tmp_path / "missing.duckdb"), "read_only": True},
            "artifacts": {"roots": [str(root)]},
        },
    )
    client = TestClient(app)

    assert client.get("/api/v1/status").json()["audit_schema_available"] is False
    response = client.get("/api/v1/scans/latest")
    assert response.status_code == 200
    assert response.json()["rows"][0]["stock_code"] == "000001.SZ"


def test_service_registry_recognizes_phase7_report_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    daily = root / "daily"
    stock = root / "stock"
    daily.mkdir(parents=True)
    stock.mkdir(parents=True)
    (daily / "daily_report.md").write_text("# Daily Research Report\n", encoding="utf-8")
    (daily / "daily_candidates.csv").write_text("stock_code\n000001.SZ\n", encoding="utf-8")
    (daily / "daily_score_summary.csv").write_text("stock_code\n000001.SZ\n", encoding="utf-8")
    (daily / "daily_metadata.json").write_text(
        '{"as_of_date":"2026-01-02","run_id":"daily-run"}\n',
        encoding="utf-8",
    )
    (stock / "stock_report.md").write_text("# Stock Research Report\n", encoding="utf-8")
    (stock / "stock_factor_values.csv").write_text(
        "stock_code,factor_name\n000001.SZ,return_20d\n",
        encoding="utf-8",
    )
    (stock / "stock_score_breakdown.csv").write_text(
        "stock_code,score_group\n000001.SZ,momentum\n",
        encoding="utf-8",
    )
    (stock / "stock_metadata.json").write_text(
        '{"stock_code":"000001.SZ","run_id":"stock-run"}\n',
        encoding="utf-8",
    )

    app = create_app(
        config_path="configs/service.yaml",
        overrides={
            "database": {"db_path": str(tmp_path / "missing.duckdb"), "read_only": True},
            "artifacts": {"roots": [str(root)]},
        },
    )
    client = TestClient(app)

    status = client.get("/api/v1/status").json()
    assert "daily_report" in status["artifacts"]["known_kinds"]
    assert "stock_report" in status["artifacts"]["known_kinds"]
    assert client.get("/api/v1/artifacts", params={"kind": "daily_report"}).json()["artifacts"]
    assert client.get("/api/v1/artifacts", params={"kind": "stock_report"}).json()["artifacts"]
