from pathlib import Path
import shutil

import duckdb
import pytest

from ashare.fixtures.builder import build_fixtures
from ashare.ingest.announcements import ingest_announcements
from ashare.ingest.local import ingest_local
from ashare.llm.parser import make_evidence_id, make_parse_id, parse_announcements


def _phase2_db(tmp_path: Path) -> tuple[Path, Path]:
    fixture_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(fixture_dir)
    ingest_local(fixture_dir, db_path)
    ingest_announcements(
        db_path=db_path,
        source="csv",
        source_tag="phase2-fixture",
        input_csv=fixture_dir / "announcements.csv",
        body_dir=fixture_dir / "announcement_bodies",
        start_date="2026-01-05",
        end_date="2026-03-31",
        raw_output_dir=tmp_path / "raw",
        overwrite=True,
    )
    return fixture_dir, db_path


def test_parse_id_and_evidence_id_are_stable() -> None:
    parse_id = make_parse_id("run-1", "phase2-fixture", "ann-1")
    evidence_id = make_evidence_id(
        parse_id=parse_id,
        item_type="key_evidence",
        item_index=0,
        evidence_text="证据",
    )

    assert parse_id == make_parse_id("run-1", "phase2-fixture", "ann-1")
    assert evidence_id == make_evidence_id(
        parse_id=parse_id,
        item_type="key_evidence",
        item_index=0,
        evidence_text="证据",
    )


def test_parse_announcements_writes_results_evidence_and_no_factor_values(
    tmp_path: Path,
) -> None:
    fixture_dir, db_path = _phase2_db(tmp_path)

    summary = parse_announcements(
        db_path=db_path,
        start_date="2026-01-06",
        end_date="2026-03-31",
        as_of="2026-03-31",
        source_tag="phase2-fixture",
        parse_run_id="phase2-fixture-parse",
        llm_mode="fixture",
        fixture_response_dir=fixture_dir / "llm_responses",
        model="fixture-llm",
        overwrite=False,
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        result_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM announcement_llm_results
            WHERE parse_run_id = 'phase2-fixture-parse'
              AND status = 'success'
              AND schema_version = 'phase2.v1'
              AND confidence BETWEEN 0.0 AND 1.0
            """
        ).fetchone()[0]
        evidence_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM announcement_llm_evidence
            WHERE locator_status IN ('exact', 'normalized')
            """
        ).fetchone()[0]
        evidence_created_at = connection.execute(
            """
            SELECT COUNT(*)
            FROM announcement_llm_evidence
            WHERE created_at IS NOT NULL
            """
        ).fetchone()[0]
        llm_factor_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM factor_values
            WHERE factor_name LIKE 'llm_%'
               OR factor_name LIKE 'announcement_llm_%'
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert summary.announcement_count == 3
    assert summary.success_count == 3
    assert summary.failed_count == 0
    assert result_rows == 3
    assert evidence_rows > 0
    assert evidence_created_at == evidence_rows
    assert llm_factor_rows == 0


def test_parse_run_duplicate_fails_without_overwrite_and_overwrite_replaces_rows(
    tmp_path: Path,
) -> None:
    fixture_dir, db_path = _phase2_db(tmp_path)
    kwargs = {
        "db_path": db_path,
        "start_date": "2026-01-06",
        "end_date": "2026-03-31",
        "as_of": "2026-03-31",
        "source_tag": "phase2-fixture",
        "parse_run_id": "phase2-fixture-parse",
        "llm_mode": "fixture",
        "fixture_response_dir": fixture_dir / "llm_responses",
        "model": "fixture-llm",
    }

    parse_announcements(**kwargs, overwrite=False)
    with pytest.raises(ValueError, match="parse_run_id already exists"):
        parse_announcements(**kwargs, overwrite=False)
    parse_announcements(**kwargs, overwrite=True)

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        results = connection.execute(
            "SELECT COUNT(*) FROM announcement_llm_results WHERE parse_run_id = ?",
            ["phase2-fixture-parse"],
        ).fetchone()[0]
        evidence = connection.execute(
            """
            SELECT COUNT(*)
            FROM announcement_llm_evidence
            WHERE parse_id IN (
                SELECT parse_id
                FROM announcement_llm_results
                WHERE parse_run_id = ?
            )
            """,
            ["phase2-fixture-parse"],
        ).fetchone()[0]
    finally:
        connection.close()

    assert results == 3
    assert evidence > 0


def test_parse_announcements_filters_by_effective_date_and_as_of(tmp_path: Path) -> None:
    fixture_dir, db_path = _phase2_db(tmp_path)

    by_effective_date = parse_announcements(
        db_path=db_path,
        start_date="2026-01-06",
        end_date="2026-01-06",
        source_tag="phase2-fixture",
        parse_run_id="effective-only",
        llm_mode="fixture",
        fixture_response_dir=fixture_dir / "llm_responses",
        model="fixture-llm",
    )
    before_visible = parse_announcements(
        db_path=db_path,
        start_date="2026-01-06",
        end_date="2026-03-31",
        as_of="2026-01-05",
        source_tag="phase2-fixture",
        parse_run_id="before-visible",
        llm_mode="fixture",
        fixture_response_dir=fixture_dir / "llm_responses",
        model="fixture-llm",
    )

    assert by_effective_date.announcement_count == 1
    assert before_visible.announcement_count == 0


def test_parse_announcements_records_missing_body_and_skips_non_whitelist(
    tmp_path: Path,
) -> None:
    fixture_dir, db_path = _phase2_db(tmp_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            UPDATE announcements
            SET raw_path = NULL
            WHERE source_tag = 'phase2-fixture'
              AND announcement_id = 'ann-000001-forecast'
            """
        )
        connection.execute(
            """
            INSERT INTO announcements (
                announcement_id,
                source,
                source_tag,
                stock_code,
                title,
                announcement_type,
                publish_time,
                effective_date,
                url,
                raw_path,
                text_hash
            )
            SELECT
                'ann-non-whitelist',
                source,
                source_tag,
                stock_code,
                '关于召开股东大会的通知',
                'other',
                publish_time,
                effective_date,
                url,
                raw_path,
                text_hash
            FROM announcements
            WHERE source_tag = 'phase2-fixture'
              AND announcement_id = 'ann-000002-buyback'
            """
        )
    finally:
        connection.close()

    summary = parse_announcements(
        db_path=db_path,
        start_date="2026-01-06",
        end_date="2026-03-31",
        as_of="2026-03-31",
        source_tag="phase2-fixture",
        parse_run_id="missing-body",
        llm_mode="fixture",
        fixture_response_dir=fixture_dir / "llm_responses",
        model="fixture-llm",
    )
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        statuses = connection.execute(
            """
            SELECT announcement_id, status
            FROM announcement_llm_results
            WHERE parse_run_id = 'missing-body'
            ORDER BY announcement_id
            """
        ).fetchall()
    finally:
        connection.close()

    assert summary.announcement_count == 3
    assert summary.success_count == 2
    assert summary.failed_count == 1
    assert ("ann-000001-forecast", "missing_body") in statuses
    assert all(row[0] != "ann-non-whitelist" for row in statuses)


def test_parse_announcements_records_schema_invalid_without_writing_evidence(
    tmp_path: Path,
) -> None:
    fixture_dir, db_path = _phase2_db(tmp_path)
    response_dir = tmp_path / "responses"
    shutil.copytree(fixture_dir / "llm_responses", response_dir)
    (response_dir / "ann-000001-forecast.json").write_text(
        '{"schema_version":"phase2.v1","announcement_type":"earnings_forecast",'
        '"sentiment":"positive","summary":"bad","confidence":0.9,'
        '"key_evidence":[],"catalysts":[],"risks":[],"extracted_metrics":[]}',
        encoding="utf-8",
    )

    summary = parse_announcements(
        db_path=db_path,
        start_date="2026-01-06",
        end_date="2026-03-31",
        as_of="2026-03-31",
        source_tag="phase2-fixture",
        parse_run_id="schema-invalid",
        llm_mode="fixture",
        fixture_response_dir=response_dir,
        model="fixture-llm",
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        invalid = connection.execute(
            """
            SELECT status, confidence
            FROM announcement_llm_results
            WHERE parse_run_id = 'schema-invalid'
              AND announcement_id = 'ann-000001-forecast'
            """
        ).fetchone()
    finally:
        connection.close()

    assert summary.success_count == 2
    assert summary.failed_count == 1
    assert invalid == ("schema_invalid", 0.0)
