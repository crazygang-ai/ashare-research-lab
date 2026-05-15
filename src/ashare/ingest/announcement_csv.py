"""CSV announcement source for Phase 2 hard acceptance."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CSV_ANNOUNCEMENT_FIELDS = {
    "announcement_id",
    "stock_code",
    "title",
    "announcement_type",
    "publish_time",
    "url",
    "body_path",
    "body_text",
    "source",
    "source_tag",
    "effective_date",
    "raw_path",
    "text_hash",
}
REQUIRED_CSV_ANNOUNCEMENT_FIELDS = {
    "stock_code",
    "title",
    "publish_time",
}


@dataclass(frozen=True)
class CsvAnnouncement:
    announcement_id: str | None
    stock_code: str
    title: str
    raw_announcement_type: str | None
    publish_time: datetime
    url: str | None
    body_path: str | None
    body_text: str | None
    source: str | None
    source_tag: str | None


def read_announcement_csv(path: str | Path) -> list[CsvAnnouncement]:
    """Read Phase 2 CSV announcement rows with strict but fixture-friendly validation."""
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        _validate_header(csv_path, reader.fieldnames)
        return [_convert_row(csv_path, index, row) for index, row in enumerate(reader, start=2)]


def _validate_header(csv_path: Path, fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise ValueError(f"{csv_path} is empty.")

    actual = set(fieldnames)
    missing = sorted(REQUIRED_CSV_ANNOUNCEMENT_FIELDS - actual)
    unexpected = sorted(actual - CSV_ANNOUNCEMENT_FIELDS)
    if missing or unexpected:
        raise ValueError(
            f"{csv_path.name} columns are invalid; missing {missing}, unexpected {unexpected}."
        )


def _convert_row(csv_path: Path, row_number: int, raw: dict[str, str]) -> CsvAnnouncement:
    stock_code = _required(raw, "stock_code", csv_path, row_number)
    title = _required(raw, "title", csv_path, row_number)
    publish_time_raw = _required(raw, "publish_time", csv_path, row_number)
    try:
        publish_time = datetime.fromisoformat(publish_time_raw)
    except ValueError as exc:
        raise ValueError(
            f"{csv_path.name}:{row_number} publish_time must be ISO datetime."
        ) from exc

    return CsvAnnouncement(
        announcement_id=_optional(raw, "announcement_id"),
        stock_code=stock_code,
        title=title,
        raw_announcement_type=_optional(raw, "announcement_type"),
        publish_time=publish_time,
        url=_optional(raw, "url"),
        body_path=_optional(raw, "body_path"),
        body_text=_optional(raw, "body_text"),
        source=_optional(raw, "source"),
        source_tag=_optional(raw, "source_tag"),
    )


def _required(raw: dict[str, str], key: str, csv_path: Path, row_number: int) -> str:
    value = _optional(raw, key)
    if value is None:
        raise ValueError(f"{csv_path.name}:{row_number} {key} is required.")
    return value


def _optional(raw: dict[str, str], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None
