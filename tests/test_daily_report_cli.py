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


def _build_db(path: Path, *, include_prices: bool = True) -> None:
    init_db(path)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            INSERT INTO trading_calendar (trade_date, is_open, prev_trade_date, next_trade_date, source)
            VALUES ('2026-01-02', true, NULL, NULL, 'fixture')
            """
        )
        connection.executemany(
            """
            INSERT INTO universe_members (index_code, stock_code, in_date, in_effective_date, source)
            VALUES ('LOCAL', ?, '2020-01-01', '2020-01-01', 'fixture')
            """,
            [("A",), ("B",)],
        )
        connection.executemany(
            """
            INSERT INTO securities (stock_code, stock_name, exchange, list_date, source)
            VALUES (?, ?, 'SSE', '2020-01-01', 'fixture')
            """,
            [("A", "Alpha"), ("B", "Beta")],
        )
        if include_prices:
            connection.executemany(
                """
                INSERT INTO daily_prices (
                    stock_code, trade_date, open, high, low, close, volume, amount,
                    adj_factor, is_suspended, limit_up, limit_down, source
                )
                VALUES (?, '2026-01-02', 1, 1, 1, 1, 1000, 1000, 1, false, NULL, NULL, 'fixture')
                """,
                [("A",), ("B",)],
            )
        connection.executemany(
            """
            INSERT INTO valuation_daily (
                stock_code, trade_date, pe_ttm, pb, ps, dividend_yield, total_mv, float_mv, source
            )
            VALUES (?, '2026-01-02', 10, 1, 1, 0.01, 100, 90, 'fixture')
            """,
            [("A",), ("B",)],
        )
        rows = []
        for stock in ["A", "B"]:
            for factor in ["is_st", "is_suspended", "is_delisted", "low_liquidity", "return_20d"]:
                rows.append((stock, date(2026, 1, 2), factor, 0.0, date(2026, 1, 2), "factor-run"))
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
            VALUES ('risk-1', 'B', 'pledge', '2026-01-02', '2026-01-02 18:00:00',
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


def _insert_artifact_run(
    db_path: Path,
    run_id: str,
    kind: str,
    paths: dict[str, Path],
    *,
    as_of_date: str = "2026-01-02",
) -> None:
    connection = duckdb.connect(str(db_path))
    started = datetime.now(timezone.utc)
    try:
        begin_run(
            connection,
            run_id=run_id,
            as_of_date=as_of_date,
            params={"command": kind, "run_mode": "exploratory", "source_run_id": "factor-run"},
            config_hash="cfg",
            data_snapshot_id="snapshot",
            git_sha="sha",
            worktree_clean=True,
            started_at=started,
            overwrite=False,
        )
        records = artifact_records_for_paths(
            repo_root=Path.cwd(),
            run_id=run_id,
            artifact_kind=kind,
            paths=paths,
            created_at=started,
        )
        insert_artifacts(connection, records)
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


def _insert_input_artifacts(db_path: Path, root: Path) -> None:
    previous_scan_paths = _write_text_files(
        root / "previous-scan",
        {
            "candidate_list.md": "# Previous Candidate List\n",
            "candidates.csv": (
                "rank,stock_code,stock_name,industry_l1,industry_l2,selection_reason,risk_tips\n"
                "1,B,Beta,Finance,Bank,previous,none\n"
                "2,A,Alpha,Tech,Software,previous,none\n"
            ),
        },
    )
    previous_score_paths = _write_text_files(
        root / "previous-score",
        {
            "scoring_report.md": "# Previous Scoring\n",
            "scored_candidates.csv": (
                "rank,stock_code,stock_name,industry_l1,industry_l2,total_score,"
                "financial_score,valuation_score,momentum_score,event_score,risk_penalty,"
                "hard_filter_passed,selection_reason,risk_tips\n"
                "1,B,Beta,Finance,Bank,80,30,20,30,0,0,true,previous,none\n"
                "2,A,Alpha,Tech,Software,70,20,20,30,0,0,true,previous,none\n"
            ),
            "score_breakdown.csv": "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\nA,momentum,35,70,0\n",
            "factor_normalized_scores.csv": (
                "stock_code,factor_name,score_role,score_group,raw_factor_value,"
                "normalized_score,factor_weight,weighted_contribution,validation_status\n"
                "A,return_20d,positive,momentum,0.1,70,1,70,PASS\n"
            ),
            "hard_filter_exclusions.csv": "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,factor_value,exclusion_reason\n",
            "validation_gate.csv": "factor_name,validation_status,reason\nreturn_20d,PASS,\n",
            "score_metadata.json": '{"index_code":"LOCAL","top_n":2,"validation_dir":""}\n',
        },
    )
    scan_paths = _write_text_files(
        root / "scan",
        {
            "candidate_list.md": "# Candidate List\n",
            "candidates.csv": (
                "rank,stock_code,stock_name,industry_l1,industry_l2,selection_reason,risk_tips\n"
                "1,A,Alpha,Tech,Software,reason,none\n"
                "2,B,Beta,Finance,Bank,reason,none\n"
            ),
        },
    )
    score_paths = _write_text_files(
        root / "score",
        {
            "scoring_report.md": "# Scoring\n",
            "scored_candidates.csv": (
                "rank,stock_code,stock_name,industry_l1,industry_l2,total_score,"
                "financial_score,valuation_score,momentum_score,event_score,risk_penalty,"
                "hard_filter_passed,selection_reason,risk_tips\n"
                "1,A,Alpha,Tech,Software,88,40,20,28,0,0,true,score reason,none\n"
                "2,B,Beta,Finance,Bank,70,30,20,20,0,5,true,score reason,risk\n"
            ),
            "score_breakdown.csv": "stock_code,score_group,weighted_contribution,group_score,missing_factor_count\nA,momentum,45,90,0\n",
            "factor_normalized_scores.csv": (
                "stock_code,factor_name,score_role,score_group,raw_factor_value,"
                "normalized_score,factor_weight,weighted_contribution,validation_status\n"
                "A,return_20d,positive,momentum,0.2,90,1,90,PASS\n"
            ),
            "hard_filter_exclusions.csv": "as_of_date,source_run_id,index_code,stock_code,hard_filter_name,factor_value,exclusion_reason\n",
            "validation_gate.csv": "factor_name,validation_status,reason\nreturn_20d,PASS,\n",
            "score_metadata.json": '{"index_code":"LOCAL","top_n":2,"validation_dir":""}\n',
        },
    )
    backtest_paths = _write_text_files(
        root / "backtest",
        {
            "backtest_report.md": "# Backtest\n",
            "metrics.csv": "total_return,max_drawdown,total_cost\n0.1,-0.02,1.0\n",
            "target_weights.csv": "signal_date,stock_code,target_weight\n2026-01-02,A,0.5\n",
            "holdings.csv": "trade_date,stock_code,shares\n2026-01-02,A,100\n",
        },
    )
    event_paths = _write_text_files(
        root / "event",
        {
            "event_study_report.md": "# Event\n",
            "event_summary.csv": (
                "event_source,event_type,horizon,sample_count,mean_event_return,"
                "median_event_return,mean_excess_return,win_rate,excess_win_rate\n"
                "risk_events,pledge,5,3,0.01,0.01,0.0,0.6,0.5\n"
            ),
            "event_samples.csv": "event_id,stock_code,effective_date,event_type\nrisk-1,B,2026-01-02,pledge\n",
        },
    )
    _insert_artifact_run(
        db_path,
        "scan-prev",
        "scan",
        previous_scan_paths,
        as_of_date="2026-01-01",
    )
    _insert_artifact_run(
        db_path,
        "score-prev",
        "scoring",
        previous_score_paths,
        as_of_date="2026-01-01",
    )
    _insert_artifact_run(db_path, "scan-run", "scan", scan_paths)
    _insert_artifact_run(db_path, "score-run", "scoring", score_paths)
    _insert_artifact_run(db_path, "backtest-run", "backtest", backtest_paths)
    _insert_artifact_run(db_path, "event-run", "event_study", event_paths)


def test_daily_report_cli_writes_report_gate_manifest_and_artifact_index(tmp_path: Path) -> None:
    db_path = tmp_path / "daily.duckdb"
    output_dir = tmp_path / "daily-output"
    _build_db(db_path)
    _insert_input_artifacts(db_path, tmp_path / "inputs")
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("stock_code,note\nA,core\nB,review\n", encoding="utf-8")

    result = _run_ashare(
        [
            "daily-report",
            "--db-path", str(db_path),
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--scan-run-id", "scan-run",
            "--score-run-id", "score-run",
            "--backtest-run-id", "backtest-run",
            "--event-study-run-id", "event-run",
            "--watchlist-file", str(watchlist),
            "--output-dir", str(output_dir),
            "--run-id", "daily-run",
        ]
    )

    assert "daily report is for research only" in result.stdout
    for filename in [
        "daily_report.md",
        "daily_candidates.csv",
        "daily_score_summary.csv",
        "daily_factor_contributions.csv",
        "daily_risk_summary.csv",
        "daily_changes.csv",
        "daily_validation_gate_summary.csv",
        "daily_watchlist_summary.csv",
        "daily_input_artifacts.json",
        "daily_metadata.json",
        "data_quality_gate.csv",
        "data_quality_gate.json",
        "run_manifest.json",
    ]:
        assert (output_dir / filename).exists()
    markdown = (output_dir / "daily_report.md").read_text(encoding="utf-8")
    assert "Input Artifact Ids And Run Ids" in markdown
    assert "artifact_ids" in markdown
    assert "source_run_id" in markdown
    assert "input_as_of_date" in markdown
    assert "input_config_hash" in markdown
    assert "input_data_snapshot_id" in markdown
    assert "snapshot" in markdown
    assert "Validation Gate Summary" in markdown
    assert "Watchlist Summary" in markdown
    changes = (output_dir / "daily_changes.csv").read_text(encoding="utf-8")
    assert "rank_changed" in changes
    metadata = json.loads((output_dir / "daily_metadata.json").read_text(encoding="utf-8"))
    assert "scan-prev" in json.dumps(metadata, ensure_ascii=False)
    assert "score-prev" in json.dumps(metadata, ensure_ascii=False)
    scan_input = next(item for item in metadata["input_artifacts"] if item["run_id"] == "scan-run")
    assert scan_input["run"]["source_run_id"] == "factor-run"
    assert scan_input["run"]["as_of_date"] == "2026-01-02"
    assert scan_input["run"]["config_hash"] == "cfg"
    assert scan_input["run"]["data_snapshot_id"] == "snapshot"

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        status = connection.execute(
            "SELECT status FROM research_runs WHERE run_id = 'daily-run'"
        ).fetchone()[0]
        input_count = connection.execute(
            "SELECT COUNT(*) FROM research_run_inputs WHERE run_id = 'daily-run'"
        ).fetchone()[0]
        kinds = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT artifact_kind FROM research_artifacts WHERE run_id = 'daily-run'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert status == "succeeded"
    assert input_count > 0
    assert {"daily_report", "data_quality_gate"}.issubset(kinds)
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "daily-run"
    assert manifest["status"] == "succeeded"


def test_daily_report_cli_filters_recent_events_by_data_source(tmp_path: Path) -> None:
    db_path = tmp_path / "daily_source.duckdb"
    output_dir = tmp_path / "daily-source-output"
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
            VALUES ('risk-other', 'B', 'pledge', '2026-01-02', '2026-01-02 18:00:00',
                    '2026-01-02', '{}'::JSON, 'other-source')
            """
        )
    finally:
        connection.close()
    _insert_input_artifacts(db_path, tmp_path / "inputs")

    _run_ashare(
        [
            "daily-report",
            "--db-path", str(db_path),
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--scan-run-id", "scan-run",
            "--score-run-id", "score-run",
            "--backtest-run-id", "backtest-run",
            "--event-study-run-id", "event-run",
            "--data-source", "fixture",
            "--output-dir", str(output_dir),
            "--run-id", "daily-source-run",
        ]
    )

    risk_summary = (output_dir / "daily_risk_summary.csv").read_text(encoding="utf-8")
    assert "ann-1" in risk_summary
    assert "risk-1" in risk_summary
    assert "ann-other" not in risk_summary
    assert "risk-other" not in risk_summary


def test_daily_report_formal_blocks_on_data_quality_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "daily_fail.duckdb"
    output_dir = tmp_path / "daily-fail-output"
    audit_config = tmp_path / "audit.yaml"
    audit_config.write_text(
        """
version: phase5.v1
run_tracking:
  enabled: true
  default_run_mode: exploratory
  formal_requires_clean_worktree: false
  fail_on_duplicate_run_id: true
  manifest_filename: run_manifest.json
artifacts:
  default_root: data/reports/generated
  write_manifest: true
  index_files: true
  hash_files: true
  csv_row_count: true
data_fingerprint:
  full_file_hash: true
  duckdb_table_mode: metadata
  max_dirty_files: 50
factor_values:
  duplicate_policy: fail
  overwrite_requires_flag: true
daily_report:
  data_quality:
    allow_missing_announcements: true
    allow_missing_risk_events: true
""".lstrip(),
        encoding="utf-8",
    )
    _build_db(db_path, include_prices=False)
    _insert_input_artifacts(db_path, tmp_path / "inputs")

    result = _run_ashare(
        [
            "daily-report",
            "--db-path", str(db_path),
            "--as-of", "2026-01-02",
            "--source-run-id", "factor-run",
            "--scan-run-id", "scan-run",
            "--score-run-id", "score-run",
            "--backtest-run-id", "backtest-run",
            "--event-study-run-id", "event-run",
            "--output-dir", str(output_dir),
            "--run-id", "daily-fail-run",
            "--run-mode", "formal",
            "--audit-config", str(audit_config),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "Data quality gate failed" in result.stderr
    assert (output_dir / "data_quality_gate.csv").exists()
    assert (output_dir / "run_manifest.json").exists()
    assert not (output_dir / "daily_report.md").exists()
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "daily-fail-run"
    assert manifest["status"] == "failed"
