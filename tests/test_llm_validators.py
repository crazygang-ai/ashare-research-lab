import pytest

from ashare.announcements.body_store import normalize_announcement_text
from ashare.llm.schemas import CURRENT_EXTRACTION_SCHEMA_VERSION, AnnouncementExtraction
from ashare.llm.validators import (
    CONFIDENCE_WEIGHTS,
    calculate_system_confidence,
    locate_evidence,
    locate_evidence_text,
    validate_extraction_content,
)


def _extraction(announcement_type: str = "buyback") -> AnnouncementExtraction:
    return AnnouncementExtraction.model_validate(
        {
            "schema_version": CURRENT_EXTRACTION_SCHEMA_VERSION,
            "announcement_type": announcement_type,
            "sentiment": "positive",
            "summary": "公司回购股份。",
            "key_evidence": [{"summary": "回购", "evidence_text": "公司拟回购股份"}],
            "catalysts": [
                {
                    "type": "capital_return",
                    "summary": "回购改善预期。",
                    "evidence_text": "回购金额不低于5000万元",
                }
            ],
            "risks": [],
            "extracted_metrics": [
                {
                    "metric_name": "buyback_min_amount",
                    "value": "5000万元",
                    "raw_value_text": "5000万元",
                    "evidence_text": "回购金额不低于5000万元",
                }
            ],
        }
    )


def test_validate_extraction_content_accepts_valid_json() -> None:
    content = _extraction().model_dump_json()

    extraction, parsed = validate_extraction_content(content)

    assert extraction.schema_version == CURRENT_EXTRACTION_SCHEMA_VERSION
    assert parsed["announcement_type"] == "buyback"


@pytest.mark.parametrize("content", ["not-json", "[]", '{"schema_version":"phase2.v1"}'])
def test_validate_extraction_content_rejects_invalid_json_missing_and_extra_cases(
    content: str,
) -> None:
    with pytest.raises(Exception):
        validate_extraction_content(content)


def test_evidence_exact_and_normalized_match_return_body_character_offsets() -> None:
    body = normalize_announcement_text("公司拟回购股份，回购金额\r\n不低于5000万元。")

    assert locate_evidence_text("公司拟回购股份", body) == ("exact", 0, 7)
    status, start, end = locate_evidence_text("回购金额\r\n不低于5000万元", body)
    assert status == "normalized"
    assert body[start:end] == "回购金额 不低于5000万元"


def test_confidence_uses_fixed_formula_and_reasons_keys() -> None:
    body = normalize_announcement_text("公司拟回购股份。回购金额不低于5000万元。")
    extraction = _extraction()
    located = locate_evidence(extraction, body)

    confidence, reasons = calculate_system_confidence(
        extraction=extraction,
        body_text=body,
        located_evidence=located,
        rule_announcement_type="buyback",
        whitelist=("buyback",),
    )

    assert confidence == 1.0
    assert tuple(reasons) == (
        "formula_version",
        "weights",
        "component_scores",
        "counts",
        "warnings",
    )
    assert reasons["weights"] == CONFIDENCE_WEIGHTS


def test_confidence_drops_when_evidence_missing_or_type_mismatch() -> None:
    body = "正文没有证据"
    extraction = _extraction(announcement_type="earnings_forecast")
    located = locate_evidence(extraction, body)

    confidence, reasons = calculate_system_confidence(
        extraction=extraction,
        body_text=body,
        located_evidence=located,
        rule_announcement_type="buyback",
        whitelist=("buyback", "earnings_forecast"),
    )

    assert confidence < 1.0
    assert reasons["component_scores"]["evidence_located_in_text"] == 0.0
    assert reasons["component_scores"]["announcement_type_whitelisted_and_consistent"] == 0.0
