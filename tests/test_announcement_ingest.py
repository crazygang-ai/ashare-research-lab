from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import pytest

from ashare.announcements.body_store import announcement_text_hash, normalize_announcement_text
from ashare.fixtures.builder import build_fixtures
from ashare.ingest.announcements import ingest_announcements
from ashare.ingest.local import ingest_local


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture_db(tmp_path: Path) -> tuple[Path, Path]:
    fixture_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(fixture_dir)
    ingest_local(fixture_dir, db_path)
    return fixture_dir, db_path


def test_ingest_announcements_imports_csv_saves_body_and_uses_system_effective_date(
    tmp_path: Path,
) -> None:
    fixture_dir, db_path = _fixture_db(tmp_path)

    summary = ingest_announcements(
        db_path=db_path,
        source="csv",
        source_tag="phase2-fixture",
        input_csv=fixture_dir / "announcements.csv",
        body_dir=fixture_dir / "announcement_bodies",
        start_date="2026-01-05",
        end_date="2026-03-31",
        raw_output_dir=tmp_path / "raw",
        overwrite=False,
        allow_missing_body=False,
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT announcement_id, source, source_tag, announcement_type,
                   publish_time, effective_date, raw_path, text_hash
            FROM announcements
            WHERE source_tag = 'phase2-fixture'
            ORDER BY announcement_id
            """
        ).fetchall()
    finally:
        connection.close()

    assert summary.inserted_rows == 3
    assert {row[1] for row in rows} == {"csv"}
    assert {row[2] for row in rows} == {"phase2-fixture"}
    first = next(row for row in rows if row[0] == "ann-000001-forecast")
    assert first[3] == "earnings_forecast"
    assert first[5].isoformat() == "2026-01-06"
    raw_path = Path(first[6])
    normalized_body = raw_path.read_text(encoding="utf-8")
    assert raw_path.is_file()
    assert normalized_body == normalize_announcement_text(normalized_body)
    assert first[7] == announcement_text_hash(normalized_body)


def test_ingest_announcements_is_idempotent_for_same_text_hash(tmp_path: Path) -> None:
    fixture_dir, db_path = _fixture_db(tmp_path)
    kwargs = {
        "db_path": db_path,
        "source": "csv",
        "source_tag": "phase2-fixture",
        "input_csv": fixture_dir / "announcements.csv",
        "body_dir": fixture_dir / "announcement_bodies",
        "start_date": "2026-01-05",
        "end_date": "2026-03-31",
        "raw_output_dir": tmp_path / "raw",
        "overwrite": False,
        "allow_missing_body": False,
    }

    first = ingest_announcements(**kwargs)
    second = ingest_announcements(**kwargs)

    assert first.inserted_rows == 3
    assert second.inserted_rows == 0
    assert second.skipped_rows == 3


def test_ingest_announcements_duplicate_changed_hash_fails_without_overwrite(
    tmp_path: Path,
) -> None:
    _, db_path = _fixture_db(tmp_path)
    csv_path = tmp_path / "announcements.csv"
    rows = [
        {
            "announcement_id": "ann-dup",
            "stock_code": "000001.SZ",
            "title": "2025年度业绩预告",
            "announcement_type": "earnings_forecast",
            "publish_time": "2026-01-05 18:00:00",
            "url": "https://example.invalid/ann-dup",
            "body_text": "第一次正文",
        }
    ]
    _write_csv(csv_path, rows)
    ingest_announcements(
        db_path=db_path,
        source="csv",
        source_tag="phase2-fixture",
        input_csv=csv_path,
        body_dir=None,
        start_date="2026-01-05",
        end_date="2026-01-05",
        raw_output_dir=tmp_path / "raw",
    )
    rows[0]["body_text"] = "第二次正文"
    _write_csv(csv_path, rows)

    with pytest.raises(ValueError, match="different text_hash"):
        ingest_announcements(
            db_path=db_path,
            source="csv",
            source_tag="phase2-fixture",
            input_csv=csv_path,
            body_dir=None,
            start_date="2026-01-05",
            end_date="2026-01-05",
            raw_output_dir=tmp_path / "raw",
        )


def test_ingest_announcements_body_text_takes_priority_over_body_path(tmp_path: Path) -> None:
    _, db_path = _fixture_db(tmp_path)
    body_dir = tmp_path / "bodies"
    body_dir.mkdir()
    (body_dir / "body.txt").write_text("path正文", encoding="utf-8")
    csv_path = tmp_path / "announcements.csv"
    _write_csv(
        csv_path,
        [
            {
                "stock_code": "000001.SZ",
                "title": "关于回购公司股份方案的公告",
                "announcement_type": "buyback",
                "publish_time": "2026-01-05 18:00:00",
                "url": "https://example.invalid/body-priority",
                "body_path": "body.txt",
                "body_text": "inline正文",
            }
        ],
    )

    ingest_announcements(
        db_path=db_path,
        source="csv",
        source_tag="priority",
        input_csv=csv_path,
        body_dir=body_dir,
        start_date="2026-01-05",
        end_date="2026-01-05",
        raw_output_dir=tmp_path / "raw",
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        raw_path = connection.execute(
            "SELECT raw_path FROM announcements WHERE source_tag = 'priority'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert Path(raw_path).read_text(encoding="utf-8") == "inline正文"


def test_ingest_announcements_missing_body_fails_by_default(tmp_path: Path) -> None:
    _, db_path = _fixture_db(tmp_path)
    csv_path = tmp_path / "announcements.csv"
    _write_csv(
        csv_path,
        [
            {
                "stock_code": "000001.SZ",
                "title": "2025年度业绩预告",
                "announcement_type": "earnings_forecast",
                "publish_time": "2026-01-05 18:00:00",
                "url": "https://example.invalid/missing-body",
            }
        ],
    )

    with pytest.raises(ValueError, match="body is missing"):
        ingest_announcements(
            db_path=db_path,
            source="csv",
            source_tag="missing",
            input_csv=csv_path,
            body_dir=None,
            start_date="2026-01-05",
            end_date="2026-01-05",
            raw_output_dir=tmp_path / "raw",
        )


def test_missing_announcement_id_hash_includes_source_tag_and_body_hash(tmp_path: Path) -> None:
    _, db_path = _fixture_db(tmp_path)
    csv_path = tmp_path / "announcements.csv"
    _write_csv(
        csv_path,
        [
            {
                "stock_code": "000001.SZ",
                "title": "2025年度业绩预告",
                "announcement_type": "earnings_forecast",
                "publish_time": "2026-01-05 18:00:00",
                "url": "https://example.invalid/hash",
                "body_text": "同一正文",
            }
        ],
    )

    for source_tag in ["tag-a", "tag-b"]:
        ingest_announcements(
            db_path=db_path,
            source="csv",
            source_tag=source_tag,
            input_csv=csv_path,
            body_dir=None,
            start_date="2026-01-05",
            end_date="2026-01-05",
            raw_output_dir=tmp_path / "raw",
        )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        ids = connection.execute(
            """
            SELECT source_tag, announcement_id, text_hash
            FROM announcements
            WHERE source_tag IN ('tag-a', 'tag-b')
            ORDER BY source_tag
            """
        ).fetchall()
    finally:
        connection.close()

    assert ids[0][1] != ids[1][1]
    assert ids[0][2] == ids[1][2] == announcement_text_hash("同一正文")
