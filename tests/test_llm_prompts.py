from datetime import date, datetime

from ashare.llm.prompts import build_extraction_prompt, extraction_json_schema
from ashare.llm.schemas import AnnouncementExtraction


def test_prompt_embeds_schema_generated_from_pydantic(monkeypatch) -> None:
    called = False
    original = AnnouncementExtraction.model_json_schema

    def spy_model_json_schema(cls, *args, **kwargs):
        nonlocal called
        called = True
        return original(*args, **kwargs)

    monkeypatch.setattr(
        AnnouncementExtraction,
        "model_json_schema",
        classmethod(spy_model_json_schema),
    )

    prompt = build_extraction_prompt(
        announcement_id="ann-1",
        stock_code="000001.SZ",
        title="关于回购公司股份方案的公告",
        announcement_type="buyback",
        publish_time=datetime(2026, 1, 5, 18, 0),
        effective_date=date(2026, 1, 6),
        body_text="公告正文",
    )

    assert called
    assert '"announcement_type"' in prompt
    assert "公告正文" in prompt


def test_extraction_json_schema_matches_pydantic_model() -> None:
    assert extraction_json_schema() == AnnouncementExtraction.model_json_schema()
