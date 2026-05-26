from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess

import duckdb

from ashare.audit.artifacts import artifact_records_for_paths
from ashare.audit.run_store import begin_run, complete_run, insert_artifacts
from ashare.storage.db import init_db


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["ashare", *args], check=check, capture_output=True, text=True)


def _build_db(path: Path) -> None:
    init_db(path)
    connection = duckdb.connect(str(path))
    try:
        connection.executemany(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date)
            VALUES (?, ?, 'SSE', '2020-01-01')
            """,
            [("A", "Alpha"), ("B", "Beta")],
        )
        connection.executemany(
            """
            INSERT INTO industry_classifications (
                stock_code, industry_standard, industry_l1, industry_l2,
                in_date, in_effective_date, version, source
            )
            VALUES (?, 'CSRC', ?, ?, '2020-01-01', '2020-01-01', 'v1', 'fixture')
            """,
            [("A", "Tech", "Software"), ("B", "Finance", "Bank")],
        )
        connection.executemany(
            """
            INSERT INTO universe_members (index_code, stock_code, in_date, in_effective_date, source)
            VALUES ('LOCAL', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [("A",), ("B",)],
        )
        rows = []
        for stock in ["A", "B"]:
            rows.extend(
                [
                    (stock, date(2026, 1, 2), "return_20d", 0.2, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "revenue_yoy", 0.1, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "pe_ttm_percentile", 0.3, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "is_st", 0.0, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "is_suspended", 0.0, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "is_delisted", 0.0, date(2026, 1, 2), "factor-run"),
                    (stock, date(2026, 1, 2), "low_liquidity", 0.0, date(2026, 1, 2), "factor-run"),
                ]
            )
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            """
            INSERT INTO announcements (
                announcement_id, source, source_tag, stock_code, title, announcement_type,
                publish_time, effective_date, url, raw_path, text_hash
            )
            VALUES ('ann-1', 'fixture', 'fixture', 'A', 'Alpha buyback', 'buyback',
                    '2026-01-01 18:00:00', '2026-01-02', '', '', 'hash')
            """
        )
        connection.execute(
            """
            INSERT INTO risk_events (
                event_id, stock_code, event_type, event_date, publish_time, effective_date,
                payload_json, source
            )
            VALUES ('risk-1', 'A', 'pledge', '2026-01-02', '2026-01-02 18:00:00',
                    '2026-01-02', '{}'::JSON, 'fixture')
            """
        )
    finally:
        connection.close()


def _write_text_files(directory: Path, files: dict[str, str]) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for filename, text in files.items():
        path = directory / filename
        path.write_text(text, encoding="utf-8")
        paths[filename] = path
    return paths


def _insert_artifact_run(db_path: Path, run_id: str, kind: str, paths: dict[str, Path]) -> None:
    connection = duckdb.connect(str(db_path))
    started = datetime.now(timezone.utc)
    try:
        begin_run(
            connection,
            run_id=run_id,
            as_of_date="2026-01-02",
            params={"command": kind, "run_mode": "exploratory", "source_run_id": "factor-run"},
            config_hash="cfg",
            data_snapshot_id="snapshot",
            git_sha="sha",
            worktree_clean=True,
            started_at=started,
            overwrite=False,
        )
        insert_artifacts(
            connection,
            artifact_records_for_paths(
                repo_root=Path.cwd(),
                run_id=run_id,
                artifact_kind=kind,
                paths=paths,
                created_at=started,
            ),
        )
        complete_run(
            connection,
            run_id=run_id,
            status="succeeded",
            params={"command": kind, "run_mode": "exploratory", "source_run_id": "factor-run"},
            config_hash="cfg",
            data_snapshot_id="snapshot",
            finished_at=started,
            error=None,
        )
    finally:
        connection.close()


def test_stock_report_cli_writes_single_stock_report_and_audit_index(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.duckdb"
    output_dir = tmp_path / "stock-output"
    _build_db(db_path)
    score_paths = _write_text_files(
        tmp_path / "score",
        {
            "scoring_report.md": "# Scoring\n",
            "scored_candidates.csv": (
                "rank,stock_code,total_score,hard_filter_passed,selection_reason,risk_tips\n"
                "1,A,88,true,score reason,none\n"
            ),
            "score_breakdown.csv": (
                "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\n"
                "A,momentum,45,90,0\n"
            ),
            "factor_normalized_scores.csv": (
                "stock_code,factor_name,score_group,raw_factor_value,normalized_score,"
                "weighted_contribution,validation_status\n"
                "A,return_20d,momentum,0.2,90,45,PASS\n"
            ),
            "hard_filter_exclusions.csv": "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,factor_value,exclusion_reason\n",
            "score_metadata.json": '{"index_code":"LOCAL"}\n',
        },
    )
    _insert_artifact_run(db_path, "score-run", "scoring", score_paths)

    result = _run_ashare(
        [
            "stock-report",
            "--db-path", str(db_path),
            "--code", "A",
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--score-run-id", "score-run",
            "--output-dir", str(output_dir),
            "--run-id", "stock-run",
        ]
    )

    assert "stock report is for research only" in result.stdout
    for filename in [
        "stock_report.md",
        "stock_factor_values.csv",
        "stock_score_breakdown.csv",
        "stock_risk_flags.csv",
        "stock_recent_announcements.csv",
        "stock_metadata.json",
        "run_manifest.json",
    ]:
        assert (output_dir / filename).exists()
    markdown = (output_dir / "stock_report.md").read_text(encoding="utf-8")
    assert "Input Artifact Ids And Run Ids" in markdown
    assert "artifact_ids" in markdown
    assert "source_run_id" in markdown
    assert "input_as_of_date" in markdown
    assert "input_config_hash" in markdown
    assert "input_data_snapshot_id" in markdown
    assert "snapshot" in markdown
    metadata = json.loads((output_dir / "stock_metadata.json").read_text(encoding="utf-8"))
    score_input = next(item for item in metadata["input_artifacts"] if item["run_id"] == "score-run")
    assert score_input["run"]["source_run_id"] == "factor-run"
    assert score_input["run"]["as_of_date"] == "2026-01-02"
    assert score_input["run"]["config_hash"] == "cfg"
    assert score_input["run"]["data_snapshot_id"] == "snapshot"

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        status = connection.execute(
            "SELECT status FROM research_runs WHERE run_id = 'stock-run'"
        ).fetchone()[0]
        input_count = connection.execute(
            "SELECT COUNT(*) FROM research_run_inputs WHERE run_id = 'stock-run'"
        ).fetchone()[0]
        kinds = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT artifact_kind FROM research_artifacts WHERE run_id = 'stock-run'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert status == "succeeded"
    assert input_count > 0
    assert "stock_report" in kinds
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "stock-run"
    assert manifest["status"] == "succeeded"


def test_stock_report_cli_filters_recent_events_by_score_data_source(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_source.duckdb"
    output_dir = tmp_path / "stock-source-output"
    _build_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            INSERT INTO announcements (
                announcement_id, source, source_tag, stock_code, title, announcement_type,
                publish_time, effective_date, url, raw_path, text_hash
            )
            VALUES ('ann-other', 'csv', 'other-source', 'A', 'Other buyback', 'buyback',
                    '2026-01-01 18:00:00', '2026-01-02', '', '', 'hash-other')
            """
        )
        connection.execute(
            """
            INSERT INTO risk_events (
                event_id, stock_code, event_type, event_date, publish_time, effective_date,
                payload_json, source
            )
            VALUES ('risk-other', 'A', 'pledge', '2026-01-02', '2026-01-02 18:00:00',
                    '2026-01-02', '{}'::JSON, 'other-source')
            """
        )
    finally:
        connection.close()
    score_paths = _write_text_files(
        tmp_path / "score-source",
        {
            "scoring_report.md": "# Scoring\n",
            "scored_candidates.csv": (
                "rank,stock_code,total_score,hard_filter_passed,selection_reason,risk_tips\n"
                "1,A,88,true,score reason,none\n"
            ),
            "score_breakdown.csv": (
                "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\n"
                "A,momentum,45,90,0\n"
            ),
            "factor_normalized_scores.csv": (
                "stock_code,factor_name,score_group,raw_factor_value,normalized_score,"
                "weighted_contribution,validation_status\n"
                "A,return_20d,momentum,0.2,90,45,PASS\n"
            ),
            "hard_filter_exclusions.csv": "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,factor_value,exclusion_reason\n",
            "score_metadata.json": '{"index_code":"LOCAL","data_source":"fixture"}\n',
        },
    )
    _insert_artifact_run(db_path, "score-source-run", "scoring", score_paths)

    _run_ashare(
        [
            "stock-report",
            "--db-path", str(db_path),
            "--code", "A",
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--score-run-id", "score-source-run",
            "--output-dir", str(output_dir),
            "--run-id", "stock-source-run",
        ]
    )

    announcements = (output_dir / "stock_recent_announcements.csv").read_text(encoding="utf-8")
    risk_flags = (output_dir / "stock_risk_flags.csv").read_text(encoding="utf-8")
    assert "ann-1" in announcements
    assert "ann-other" not in announcements
    assert "risk-1" in risk_flags
    assert "risk-other" not in risk_flags


def test_stock_report_cli_generates_batch_reports_from_watchlist_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_watchlist.duckdb"
    output_dir = tmp_path / "stock-watchlist-output"
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("stock_code,note\nA,core\nB,review\n", encoding="utf-8")
    _build_db(db_path)
    score_paths = _write_text_files(
        tmp_path / "score-watchlist",
        {
            "scoring_report.md": "# Scoring\n",
            "scored_candidates.csv": (
                "rank,stock_code,total_score,hard_filter_passed,selection_reason,risk_tips\n"
                "1,A,88,true,score reason,none\n"
                "2,B,70,true,watch reason,risk\n"
            ),
            "score_breakdown.csv": (
                "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\n"
                "A,momentum,45,90,0\n"
                "B,momentum,35,70,0\n"
            ),
            "factor_normalized_scores.csv": (
                "stock_code,factor_name,score_group,raw_factor_value,normalized_score,"
                "weighted_contribution,validation_status\n"
                "A,return_20d,momentum,0.2,90,45,PASS\n"
                "B,return_20d,momentum,0.1,70,35,PASS\n"
            ),
            "hard_filter_exclusions.csv": "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,factor_value,exclusion_reason\n",
            "score_metadata.json": '{"index_code":"LOCAL"}\n',
        },
    )
    _insert_artifact_run(db_path, "score-watchlist-run", "scoring", score_paths)

    result = _run_ashare(
        [
            "stock-report",
            "--db-path", str(db_path),
            "--watchlist-file", str(watchlist),
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--score-run-id", "score-watchlist-run",
            "--output-dir", str(output_dir),
            "--run-id", "stock-watchlist-run",
        ]
    )

    assert "watchlist_count: 2" in result.stdout
    assert (output_dir / "stock-A" / "stock_report.md").exists()
    assert (output_dir / "stock-B" / "stock_report.md").exists()
    assert "risk_event" in (output_dir / "stock-A" / "stock_risk_flags.csv").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "stock-watchlist-run"
    assert manifest["status"] == "succeeded"


def test_stock_report_cli_requires_scoring_artifact(tmp_path: Path) -> None:
    db_path = tmp_path / "stock_missing.duckdb"
    _build_db(db_path)

    result = _run_ashare(
        [
            "stock-report",
            "--db-path", str(db_path),
            "--code", "A",
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--score-run-id", "missing-score-run",
            "--output-dir", str(tmp_path / "missing"),
            "--run-id", "stock-missing-run",
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "Required scoring artifact" in result.stderr
