"""Pydantic schemas for Phase 2 announcement extraction outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CURRENT_EXTRACTION_SCHEMA_VERSION = "phase2.v1"

AnnouncementType = Literal[
    "earnings_forecast",
    "earnings_report",
    "buyback",
    "shareholder_reduce",
    "inquiry_letter",
    "regulatory_penalty",
    "material_contract",
    "material_litigation",
    "non_standard_audit",
]
Sentiment = Literal["positive", "neutral", "negative", "mixed", "unknown"]
FORBIDDEN_LLM_FIELDS = {
    "score",
    "total_score",
    "target_price",
    "buy",
    "sell",
    "recommendation",
    "confidence",
}


class StrictExtractionModel(BaseModel):
    """Base model forbidding extra fields and disallowed recommendation fields."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_llm_fields(cls, data: Any) -> Any:
        _reject_forbidden_keys(data)
        return data


class KeyEvidence(StrictExtractionModel):
    summary: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class Catalyst(StrictExtractionModel):
    type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class Risk(StrictExtractionModel):
    type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class ExtractedMetric(StrictExtractionModel):
    metric_name: str = Field(min_length=1)
    value: str | float | int
    evidence_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    raw_value_text: str | None = None


class AnnouncementExtraction(StrictExtractionModel):
    schema_version: Literal["phase2.v1"]
    announcement_type: AnnouncementType
    sentiment: Sentiment
    summary: str = Field(min_length=1)
    key_evidence: list[KeyEvidence] = Field(default_factory=list)
    catalysts: list[Catalyst] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    extracted_metrics: list[ExtractedMetric] = Field(default_factory=list)


def validate_schema_version(schema_version: str) -> None:
    """Fail fast for unsupported historical extraction schema versions."""
    if schema_version != CURRENT_EXTRACTION_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported announcement extraction schema_version: {schema_version!r}"
        )


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_LLM_FIELDS:
                raise ValueError(f"Forbidden LLM output field: {key}")
            _reject_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)
