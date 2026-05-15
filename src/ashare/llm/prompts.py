"""Prompt construction for Phase 2 announcement extraction."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any

from ashare.announcements.body_store import normalize_announcement_text
from ashare.llm.schemas import AnnouncementExtraction, CURRENT_EXTRACTION_SCHEMA_VERSION


PROMPT_TEMPLATE_VERSION = "phase2.prompt.v1"


def extraction_json_schema() -> dict[str, Any]:
    """Return JSON Schema generated from the Pydantic extraction model."""
    return AnnouncementExtraction.model_json_schema()


def build_extraction_prompt(
    *,
    announcement_id: str,
    stock_code: str,
    title: str,
    announcement_type: str,
    publish_time: datetime,
    effective_date: date,
    body_text: str,
    max_input_chars: int = 20_000,
) -> str:
    """Build a deterministic prompt embedding the Pydantic-generated JSON Schema."""
    normalized_body = normalize_announcement_text(body_text)
    truncated_body = normalized_body[:max_input_chars]
    schema = json.dumps(extraction_json_schema(), ensure_ascii=False, sort_keys=True)
    return (
        f"Template: {PROMPT_TEMPLATE_VERSION}\n"
        "Task: Extract structured research evidence from one A-share announcement.\n"
        "Rules:\n"
        "- Return one JSON object only, with no markdown or commentary.\n"
        "- Use the JSON Schema below as the only output contract.\n"
        "- Do not provide buy, sell, recommendation, target price, score, or confidence fields.\n"
        "- Evidence text must be copied from the announcement body when possible.\n"
        f"- schema_version must be {CURRENT_EXTRACTION_SCHEMA_VERSION}.\n"
        "\n"
        "JSON Schema:\n"
        f"{schema}\n"
        "\n"
        "Announcement metadata:\n"
        f"announcement_id: {announcement_id}\n"
        f"stock_code: {stock_code}\n"
        f"title: {title}\n"
        f"rule_announcement_type: {announcement_type}\n"
        f"publish_time: {publish_time.isoformat()}\n"
        f"effective_date: {effective_date.isoformat()}\n"
        "\n"
        "Announcement body:\n"
        f"{truncated_body}\n"
    )


def prompt_hash(prompt: str) -> str:
    """Return the stable SHA1 hash for a concrete prompt."""
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()


def prompt_template_hash() -> str:
    """Return a stable hash of the prompt template version and generated schema."""
    payload = json.dumps(
        {
            "template_version": PROMPT_TEMPLATE_VERSION,
            "schema": extraction_json_schema(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
