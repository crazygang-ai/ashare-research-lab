"""LLM JSON validation, evidence location and system confidence scoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from pydantic import ValidationError

from ashare.announcements.body_store import normalize_announcement_text
from ashare.announcements.rules import DEFAULT_ANNOUNCEMENT_WHITELIST
from ashare.llm.schemas import AnnouncementExtraction


CONFIDENCE_FORMULA_VERSION = "phase2.confidence.v1"
CONFIDENCE_WEIGHTS = {
    "schema_valid": 0.25,
    "required_fields_complete": 0.15,
    "evidence_present": 0.20,
    "evidence_located_in_text": 0.25,
    "announcement_type_whitelisted_and_consistent": 0.10,
    "numeric_metrics_match_text": 0.05,
}
CONFIDENCE_REASON_KEYS = (
    "formula_version",
    "weights",
    "component_scores",
    "counts",
    "warnings",
)


@dataclass(frozen=True)
class EvidenceReference:
    item_type: str
    item_index: int
    evidence_text: str
    page: int | None


@dataclass(frozen=True)
class LocatedEvidence:
    item_type: str
    item_index: int
    evidence_text: str
    page: int | None
    char_start: int | None
    char_end: int | None
    locator_status: str


def parse_llm_json(content: str) -> dict[str, Any]:
    """Parse raw LLM content as a JSON object."""
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object.")
    return parsed


def validate_extraction_content(content: str) -> tuple[AnnouncementExtraction, dict[str, Any]]:
    """Parse and validate one LLM response against the Pydantic schema."""
    parsed = parse_llm_json(content)
    return AnnouncementExtraction.model_validate(parsed), parsed


def collect_evidence_references(
    extraction: AnnouncementExtraction,
) -> list[EvidenceReference]:
    """Collect all model evidence references with stable per-list indexes."""
    references: list[EvidenceReference] = []
    for index, item in enumerate(extraction.key_evidence):
        references.append(EvidenceReference("key_evidence", index, item.evidence_text, item.page))
    for index, item in enumerate(extraction.catalysts):
        references.append(EvidenceReference("catalysts", index, item.evidence_text, item.page))
    for index, item in enumerate(extraction.risks):
        references.append(EvidenceReference("risks", index, item.evidence_text, item.page))
    for index, item in enumerate(extraction.extracted_metrics):
        references.append(
            EvidenceReference("extracted_metrics", index, item.evidence_text, item.page)
        )
    return references


def locate_evidence_text(evidence_text: str, body_text: str) -> tuple[str, int | None, int | None]:
    """Locate evidence in normalized body text using exact then normalized matching."""
    if not evidence_text:
        return "missing", None, None

    exact_start = body_text.find(evidence_text)
    if exact_start >= 0:
        return "exact", exact_start, exact_start + len(evidence_text)

    normalized_evidence = normalize_announcement_text(evidence_text)
    normalized_start = body_text.find(normalized_evidence)
    if normalized_start >= 0:
        return "normalized", normalized_start, normalized_start + len(normalized_evidence)

    return "not_found", None, None


def locate_evidence(
    extraction: AnnouncementExtraction,
    body_text: str,
) -> list[LocatedEvidence]:
    """Locate all evidence references in the saved normalized announcement body."""
    normalized_body = normalize_announcement_text(body_text)
    located: list[LocatedEvidence] = []
    for reference in collect_evidence_references(extraction):
        status, start, end = locate_evidence_text(reference.evidence_text, normalized_body)
        located.append(
            LocatedEvidence(
                item_type=reference.item_type,
                item_index=reference.item_index,
                evidence_text=reference.evidence_text,
                page=reference.page,
                char_start=start,
                char_end=end,
                locator_status=status,
            )
        )
    return located


def invalid_confidence_reasons(error: str) -> dict[str, Any]:
    """Return fixed-key confidence reasons for schema-invalid or LLM-error outputs."""
    reasons = {
        "formula_version": CONFIDENCE_FORMULA_VERSION,
        "weights": dict(CONFIDENCE_WEIGHTS),
        "component_scores": {name: 0.0 for name in CONFIDENCE_WEIGHTS},
        "counts": {},
        "warnings": [error],
    }
    _assert_reason_keys(reasons)
    return reasons


def calculate_system_confidence(
    *,
    extraction: AnnouncementExtraction,
    body_text: str,
    located_evidence: list[LocatedEvidence],
    rule_announcement_type: str,
    whitelist: tuple[str, ...] = DEFAULT_ANNOUNCEMENT_WHITELIST,
) -> tuple[float, dict[str, Any]]:
    """Calculate deterministic Phase 2 system confidence and its component reasons."""
    normalized_body = normalize_announcement_text(body_text)
    total_items = (
        len(extraction.key_evidence)
        + len(extraction.catalysts)
        + len(extraction.risks)
        + len(extraction.extracted_metrics)
    )
    items_with_evidence = sum(1 for item in located_evidence if item.evidence_text)
    located_count = sum(
        1 for item in located_evidence if item.locator_status in {"exact", "normalized"}
    )

    core_fields = [
        extraction.schema_version,
        extraction.announcement_type,
        extraction.sentiment,
        extraction.summary,
    ]
    nonempty_core_fields = sum(1 for value in core_fields if str(value).strip())
    required_fields_score = nonempty_core_fields / 4

    if total_items == 0:
        evidence_present_score = 1.0
    else:
        evidence_present_score = items_with_evidence / total_items

    total_evidence_count = items_with_evidence
    if total_evidence_count == 0 and total_items == 0:
        evidence_located_score = 1.0
    elif total_evidence_count == 0 and total_items > 0:
        evidence_located_score = 0.0
    else:
        evidence_located_score = located_count / total_evidence_count

    type_consistent = (
        rule_announcement_type in set(whitelist)
        and extraction.announcement_type == rule_announcement_type
    )
    type_score = 1.0 if type_consistent else 0.0

    matched_metrics = _matched_numeric_metrics(extraction, normalized_body)
    total_metrics = len(extraction.extracted_metrics)
    metrics_score = 1.0 if total_metrics == 0 else matched_metrics / total_metrics

    component_scores = {
        "schema_valid": 1.0,
        "required_fields_complete": required_fields_score,
        "evidence_present": evidence_present_score,
        "evidence_located_in_text": evidence_located_score,
        "announcement_type_whitelisted_and_consistent": type_score,
        "numeric_metrics_match_text": metrics_score,
    }
    warnings: list[str] = []
    if located_count < total_evidence_count:
        warnings.append("some evidence_text values were not located in announcement body")
    if not type_consistent:
        warnings.append("llm announcement_type differs from deterministic rule type")
    if matched_metrics < total_metrics:
        warnings.append("some numeric metrics were not found in evidence or body text")

    confidence = round(
        sum(CONFIDENCE_WEIGHTS[name] * component_scores[name] for name in CONFIDENCE_WEIGHTS),
        6,
    )
    reasons = {
        "formula_version": CONFIDENCE_FORMULA_VERSION,
        "weights": dict(CONFIDENCE_WEIGHTS),
        "component_scores": component_scores,
        "counts": {
            "total_items": total_items,
            "items_with_evidence": items_with_evidence,
            "total_evidence_count": total_evidence_count,
            "located_count": located_count,
            "total_metrics": total_metrics,
            "matched_metrics": matched_metrics,
        },
        "warnings": warnings,
    }
    _assert_reason_keys(reasons)
    return confidence, reasons


def schema_error_summary(exc: Exception) -> str:
    """Return a compact schema/JSON validation error for persistence."""
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors()[:3])
    return str(exc)


def _matched_numeric_metrics(extraction: AnnouncementExtraction, normalized_body: str) -> int:
    matched = 0
    for metric in extraction.extracted_metrics:
        raw_value = metric.raw_value_text
        candidate = raw_value if raw_value not in {None, ""} else str(metric.value)
        normalized_candidate = normalize_announcement_text(str(candidate))
        normalized_evidence = normalize_announcement_text(metric.evidence_text)
        if (
            normalized_candidate
            and (
                normalized_candidate in normalized_evidence
                or normalized_candidate in normalized_body
            )
        ):
            matched += 1
    return matched


def _assert_reason_keys(reasons: dict[str, Any]) -> None:
    if tuple(reasons) != CONFIDENCE_REASON_KEYS:
        raise AssertionError("confidence_reasons keys are not stable.")
