"""Announcement body normalization and raw text storage."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path


def normalize_announcement_text(text: str) -> str:
    """Return the single Phase 2 normalized announcement text representation."""
    if text.startswith("\ufeff"):
        text = text[1:]
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def announcement_text_hash(text: str) -> str:
    """Hash normalized announcement body text with SHA256."""
    normalized = normalize_announcement_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def announcement_body_path(
    raw_output_dir: str | Path,
    source_tag: str,
    stock_code: str,
    publish_time: date | datetime,
    announcement_id: str,
) -> Path:
    """Build the deterministic raw body path for a normalized announcement body."""
    publish_date = publish_time.date() if isinstance(publish_time, datetime) else publish_time
    return (
        Path(raw_output_dir)
        / source_tag
        / stock_code
        / publish_date.isoformat()
        / f"{announcement_id}.txt"
    )


def write_announcement_body(
    *,
    raw_output_dir: str | Path,
    source_tag: str,
    stock_code: str,
    publish_time: date | datetime,
    announcement_id: str,
    body_text: str,
) -> Path:
    """Normalize and save announcement body text, returning the written path."""
    output_path = announcement_body_path(
        raw_output_dir=raw_output_dir,
        source_tag=source_tag,
        stock_code=stock_code,
        publish_time=publish_time,
        announcement_id=announcement_id,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(normalize_announcement_text(body_text), encoding="utf-8")
    return output_path
