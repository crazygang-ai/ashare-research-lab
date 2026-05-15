from ashare.announcements.rules import (
    DEFAULT_ANNOUNCEMENT_WHITELIST,
    canonicalize_announcement_type,
    match_announcement_rule,
)


def test_rules_recognize_all_phase2_whitelist_types() -> None:
    samples = {
        "earnings_forecast": "2025年度业绩预告",
        "earnings_report": "2025年度业绩快报",
        "buyback": "关于回购公司股份方案的公告",
        "shareholder_reduce": "控股股东减持计划公告",
        "inquiry_letter": "关于收到交易所问询函的公告",
        "regulatory_penalty": "关于收到行政处罚决定书的公告",
        "material_contract": "关于签署重大合同的公告",
        "material_litigation": "关于重大诉讼进展的公告",
        "non_standard_audit": "关于非标准审计意见的专项说明",
    }

    for expected_type, title in samples.items():
        match = match_announcement_rule(
            title=title,
            raw_announcement_type=None,
            whitelist=DEFAULT_ANNOUNCEMENT_WHITELIST,
        )
        assert match.announcement_type == expected_type
        assert match.selected


def test_earnings_report_synonyms_are_stable() -> None:
    for title in ["业绩快报", "定期报告摘要", "年报摘要", "半年报摘要", "一季报摘要", "三季报摘要"]:
        assert (
            canonicalize_announcement_type(title=title, raw_announcement_type=None)
            == "earnings_report"
        )


def test_non_whitelist_announcement_is_not_selected() -> None:
    match = match_announcement_rule(
        title="关于召开股东大会的通知",
        raw_announcement_type="meeting_notice",
        whitelist=DEFAULT_ANNOUNCEMENT_WHITELIST,
    )

    assert match.announcement_type == "other"
    assert not match.selected
