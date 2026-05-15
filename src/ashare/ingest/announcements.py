"""Announcement metadata ingest and normalized body storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from pathlib import Path

import duckdb

from ashare.announcements.body_store import (
    announcement_text_hash,
    normalize_announcement_text,
    write_announcement_body,
)
from ashare.announcements.rules import canonicalize_announcement_type
from ashare.ingest.announcement_csv import CsvAnnouncement, read_announcement_csv
from ashare.pit.effective_date import calculate_effective_date
from ashare.storage.db import connect, init_db


@dataclass(frozen=True)
class AnnouncementIngestSummary:
    db_path: Path
    source: str
    source_tag: str
    input_rows: int
    filtered_rows: int
    inserted_rows: int
    skipped_rows: int
    overwritten_rows: int


def ingest_announcements(
    *,
    db_path: str | Path,
    source: str,
    source_tag: str,
    input_csv: str | Path,
    body_dir: str | Path | None,
    start_date: str | date,
    end_date: str | date,
    raw_output_dir: str | Path,
    overwrite: bool = False,
    allow_missing_body: bool = False,
) -> AnnouncementIngestSummary:
    """Ingest announcement metadata and normalized body text from CSV."""
    if source != "csv":
        raise ValueError("Phase 2 announcement ingest only supports --source csv.")

    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    if parsed_start > parsed_end:
        raise ValueError("--from must be on or before --to.")

    rows = read_announcement_csv(input_csv)
    filtered_rows = [
        row for row in rows if parsed_start <= row.publish_time.date() <= parsed_end
    ]

    init_db(db_path)
    connection = connect(db_path)
    inserted = 0
    skipped = 0
    overwritten = 0
    try:
        trading_days = _open_trading_days(connection)
        if not trading_days:
            raise ValueError("trading_calendar has no open trading days.")

        connection.execute("BEGIN TRANSACTION")
        for row in filtered_rows:
            prepared = _prepare_announcement_row(
                row=row,
                source=source,
                source_tag=source_tag,
                body_dir=Path(body_dir) if body_dir is not None else None,
                raw_output_dir=raw_output_dir,
                trading_days=trading_days,
                allow_missing_body=allow_missing_body,
            )
            existing = _existing_announcement(connection, source_tag, prepared["announcement_id"])
            if existing is not None:
                existing_hash = existing["text_hash"]
                if not overwrite:
                    if existing_hash == prepared["text_hash"]:
                        skipped += 1
                        continue
                    raise ValueError(
                        "Announcement already exists with different text_hash: "
                        f"{source_tag}/{prepared['announcement_id']}"
                    )
                _delete_existing_announcement(connection, source_tag, prepared["announcement_id"])
                overwritten += 1

            _insert_announcement(connection, prepared)
            inserted += 1
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    return AnnouncementIngestSummary(
        db_path=Path(db_path),
        source=source,
        source_tag=source_tag,
        input_rows=len(rows),
        filtered_rows=len(filtered_rows),
        inserted_rows=inserted,
        skipped_rows=skipped,
        overwritten_rows=overwritten,
    )


def _prepare_announcement_row(
    *,
    row: CsvAnnouncement,
    source: str,
    source_tag: str,
    body_dir: Path | None,
    raw_output_dir: str | Path,
    trading_days: list[date],
    allow_missing_body: bool,
) -> dict[str, object]:
    body_text = _resolve_body_text(row, body_dir)
    normalized_body: str | None = None
    text_hash: str | None = None
    if body_text is not None:
        normalized_body = normalize_announcement_text(body_text)
        if not normalized_body and not allow_missing_body:
            raise ValueError(f"Announcement body is empty: {row.stock_code} {row.title}")
        if normalized_body:
            text_hash = announcement_text_hash(normalized_body)
    elif not allow_missing_body:
        raise ValueError(f"Announcement body is missing: {row.stock_code} {row.title}")

    announcement_id = row.announcement_id or _stable_announcement_id(
        source_tag=source_tag,
        stock_code=row.stock_code,
        publish_time=row.publish_time,
        title=row.title,
        url=row.url,
        text_hash=text_hash,
    )
    canonical_type = canonicalize_announcement_type(
        title=row.title,
        raw_announcement_type=row.raw_announcement_type,
    )
    effective_date = calculate_effective_date(row.publish_time, trading_days)

    raw_path: str | None = None
    if normalized_body:
        raw_path = str(
            write_announcement_body(
                raw_output_dir=raw_output_dir,
                source_tag=source_tag,
                stock_code=row.stock_code,
                publish_time=row.publish_time,
                announcement_id=announcement_id,
                body_text=normalized_body,
            )
        )

    return {
        "announcement_id": announcement_id,
        "source": source,
        "source_tag": source_tag,
        "stock_code": row.stock_code,
        "title": row.title,
        "announcement_type": canonical_type,
        "publish_time": row.publish_time,
        "effective_date": effective_date,
        "url": row.url,
        "raw_path": raw_path,
        "text_hash": text_hash,
    }


def _resolve_body_text(row: CsvAnnouncement, body_dir: Path | None) -> str | None:
    if row.body_text is not None:
        return row.body_text
    if row.body_path is None:
        return None

    body_path = Path(row.body_path)
    if not body_path.is_absolute() and body_dir is not None:
        body_path = body_dir / body_path
    return body_path.read_text(encoding="utf-8")


def _stable_announcement_id(
    *,
    source_tag: str,
    stock_code: str,
    publish_time: datetime,
    title: str,
    url: str | None,
    text_hash: str | None,
) -> str:
    payload = "|".join(
        [
            source_tag,
            stock_code,
            publish_time.isoformat(),
            normalize_announcement_text(title).lower(),
            normalize_announcement_text(url or "").lower(),
            text_hash or "",
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _existing_announcement(
    connection: duckdb.DuckDBPyConnection,
    source_tag: str,
    announcement_id: str,
) -> dict[str, object] | None:
    rows = connection.execute(
        """
        SELECT text_hash
        FROM announcements
        WHERE source_tag = ?
          AND announcement_id = ?
        """,
        [source_tag, announcement_id],
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(f"Duplicate announcement rows exist: {source_tag}/{announcement_id}")
    return {"text_hash": rows[0][0]}


def _delete_existing_announcement(
    connection: duckdb.DuckDBPyConnection,
    source_tag: str,
    announcement_id: str,
) -> None:
    connection.execute(
        "DELETE FROM announcements WHERE source_tag = ? AND announcement_id = ?",
        [source_tag, announcement_id],
    )


def _insert_announcement(
    connection: duckdb.DuckDBPyConnection,
    row: dict[str, object],
) -> None:
    columns = (
        "announcement_id",
        "source",
        "source_tag",
        "stock_code",
        "title",
        "announcement_type",
        "publish_time",
        "effective_date",
        "url",
        "raw_path",
        "text_hash",
    )
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO announcements ({', '.join(columns)}) VALUES ({placeholders})",
        [row[column] for column in columns],
    )


def _open_trading_days(connection: duckdb.DuckDBPyConnection) -> list[date]:
    rows = connection.execute(
        "SELECT trade_date FROM trading_calendar WHERE is_open = true ORDER BY trade_date"
    ).fetchall()
    return [row[0] for row in rows]


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
