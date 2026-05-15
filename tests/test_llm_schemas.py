import pytest
from pydantic import ValidationError

from ashare.llm.schemas import (
    CURRENT_EXTRACTION_SCHEMA_VERSION,
    AnnouncementExtraction,
    validate_schema_version,
)


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": CURRENT_EXTRACTION_SCHEMA_VERSION,
        "announcement_type": "buyback",
        "sentiment": "positive",
        "summary": "公司计划回购股份。",
        "key_evidence": [{"summary": "回购", "evidence_text": "公司拟回购股份"}],
        "catalysts": [],
        "risks": [],
        "extracted_metrics": [],
    }


def test_announcement_extraction_generates_json_schema() -> None:
    schema = AnnouncementExtraction.model_json_schema()

    assert schema["type"] == "object"
    assert "announcement_type" in schema["properties"]
    assert "confidence" not in str(schema)


@pytest.mark.parametrize("field", ["score", "target_price", "recommendation", "confidence"])
def test_schema_rejects_forbidden_llm_fields(field: str) -> None:
    payload = _valid_payload()
    payload[field] = "forbidden"

    with pytest.raises(ValidationError):
        AnnouncementExtraction.model_validate(payload)


def test_schema_rejects_extra_nested_fields() -> None:
    payload = _valid_payload()
    payload["risks"] = [
        {
            "type": "risk",
            "summary": "风险",
            "evidence_text": "风险证据",
            "confidence": 0.9,
        }
    ]

    with pytest.raises(ValidationError):
        AnnouncementExtraction.model_validate(payload)


def test_schema_version_must_match_phase2_v1() -> None:
    payload = _valid_payload()
    payload["schema_version"] = "phase2.v2"

    with pytest.raises(ValidationError):
        AnnouncementExtraction.model_validate(payload)
    with pytest.raises(ValueError, match="Unsupported"):
        validate_schema_version("phase2.v2")
