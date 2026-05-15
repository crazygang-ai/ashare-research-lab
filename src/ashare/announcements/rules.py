"""Deterministic announcement type canonicalization and LLM selection rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import yaml

from ashare.announcements.body_store import normalize_announcement_text


DEFAULT_ANNOUNCEMENT_WHITELIST = (
    "earnings_forecast",
    "earnings_report",
    "buyback",
    "shareholder_reduce",
    "inquiry_letter",
    "regulatory_penalty",
    "material_contract",
    "material_litigation",
    "non_standard_audit",
)


@dataclass(frozen=True)
class AnnouncementRule:
    canonical_type: str
    rule_name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class AnnouncementRuleMatch:
    announcement_type: str
    selected: bool
    rule_name: str
    matched_text: str
    reason: str


RULES: tuple[AnnouncementRule, ...] = (
    AnnouncementRule(
        "earnings_forecast",
        "earnings_forecast_keyword",
        (
            "earnings_forecast",
            "业绩预告",
            "盈利预告",
            "业绩预增",
            "业绩预减",
            "预盈",
            "预亏",
            "earnings forecast",
            "performance forecast",
        ),
    ),
    AnnouncementRule(
        "earnings_report",
        "earnings_report_keyword",
        (
            "earnings_report",
            "业绩快报",
            "定期报告摘要",
            "年报摘要",
            "半年报摘要",
            "一季报摘要",
            "三季报摘要",
            "年度报告摘要",
            "半年度报告摘要",
            "季度报告摘要",
            "earnings report",
            "annual report summary",
            "quarterly report summary",
            "periodic report summary",
        ),
    ),
    AnnouncementRule(
        "buyback",
        "buyback_keyword",
        ("buyback", "repurchase", "股份回购", "回购股份", "回购公司股份", "回购方案"),
    ),
    AnnouncementRule(
        "shareholder_reduce",
        "shareholder_reduce_keyword",
        (
            "shareholder_reduce",
            "减持",
            "减持计划",
            "股份减持",
            "股东减持",
            "shareholding reduction",
            "shareholder reduction",
        ),
    ),
    AnnouncementRule(
        "inquiry_letter",
        "inquiry_letter_keyword",
        ("inquiry_letter", "问询函", "监管问询", "交易所问询", "inquiry letter"),
    ),
    AnnouncementRule(
        "regulatory_penalty",
        "regulatory_penalty_keyword",
        ("regulatory_penalty", "行政处罚", "监管处罚", "处罚决定", "regulatory penalty"),
    ),
    AnnouncementRule(
        "material_contract",
        "material_contract_keyword",
        ("material_contract", "重大合同", "重要合同", "material contract", "significant contract"),
    ),
    AnnouncementRule(
        "material_litigation",
        "material_litigation_keyword",
        ("material_litigation", "重大诉讼", "重大仲裁", "诉讼", "仲裁", "litigation", "lawsuit"),
    ),
    AnnouncementRule(
        "non_standard_audit",
        "non_standard_audit_keyword",
        (
            "non_standard_audit",
            "非标准审计",
            "非标审计",
            "非标准无保留意见",
            "保留意见",
            "无法表示意见",
            "否定意见",
            "qualified opinion",
            "modified audit",
            "non-standard audit",
        ),
    ),
)


def load_announcement_whitelist(
    config_path: str | Path = "configs/llm.yaml",
) -> tuple[str, ...]:
    """Load the configured announcement whitelist, falling back to Phase 2 defaults."""
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_ANNOUNCEMENT_WHITELIST

    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"LLM config must be a mapping: {path}")

    whitelist = config.get("announcement_whitelist", DEFAULT_ANNOUNCEMENT_WHITELIST)
    if not isinstance(whitelist, list) or not all(isinstance(item, str) for item in whitelist):
        raise ValueError("llm.announcement_whitelist must be a list of strings.")

    return tuple(whitelist)


def canonicalize_announcement_type(
    *,
    title: str | None,
    raw_announcement_type: str | None,
) -> str:
    """Return the canonical rule type, or ``other`` when no deterministic rule matches."""
    return match_announcement_rule(
        title=title,
        raw_announcement_type=raw_announcement_type,
        whitelist=DEFAULT_ANNOUNCEMENT_WHITELIST,
    ).announcement_type


def match_announcement_rule(
    *,
    title: str | None,
    raw_announcement_type: str | None,
    whitelist: Iterable[str] = DEFAULT_ANNOUNCEMENT_WHITELIST,
) -> AnnouncementRuleMatch:
    """Match title/provider type against deterministic Phase 2 announcement rules."""
    whitelist_set = set(whitelist)
    candidates = _candidate_texts(raw_announcement_type=raw_announcement_type, title=title)

    for rule in RULES:
        for source_name, candidate in candidates:
            matched = _match_rule_patterns(rule, candidate)
            if matched is not None:
                selected = rule.canonical_type in whitelist_set
                return AnnouncementRuleMatch(
                    announcement_type=rule.canonical_type,
                    selected=selected,
                    rule_name=rule.rule_name,
                    matched_text=matched,
                    reason=f"{source_name} matched {rule.rule_name}",
                )

    return AnnouncementRuleMatch(
        announcement_type="other",
        selected=False,
        rule_name="default_other",
        matched_text="",
        reason="no whitelist rule matched",
    )


def _candidate_texts(
    *,
    raw_announcement_type: str | None,
    title: str | None,
) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    if raw_announcement_type:
        candidates.append(("provider_type", normalize_announcement_text(raw_announcement_type)))
    if title:
        candidates.append(("title", normalize_announcement_text(title)))
    return tuple(candidates)


def _match_rule_patterns(rule: AnnouncementRule, text: str) -> str | None:
    lowered = text.lower()
    for pattern in rule.patterns:
        normalized_pattern = normalize_announcement_text(pattern).lower()
        if re.search(re.escape(normalized_pattern), lowered):
            return pattern
    return None
