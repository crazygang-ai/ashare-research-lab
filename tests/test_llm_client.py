import json
from pathlib import Path

from ashare.llm.client import FixtureLLMClient


def test_fixture_llm_client_reads_default_and_variant_response(tmp_path: Path) -> None:
    response_dir = tmp_path / "responses"
    response_dir.mkdir()
    (response_dir / "ann-1.json").write_text(
        json.dumps({"schema_version": "phase2.v1", "summary": "default"}),
        encoding="utf-8",
    )
    (response_dir / "ann-1.alt.json").write_text(
        json.dumps({"schema_version": "phase2.v1", "summary": "variant"}),
        encoding="utf-8",
    )

    default = FixtureLLMClient(response_dir).complete(announcement_id="ann-1", prompt="prompt")
    variant = FixtureLLMClient(response_dir, variant="alt").complete(
        announcement_id="ann-1",
        prompt="prompt",
    )

    assert json.loads(default.content)["summary"] == "default"
    assert json.loads(variant.content)["summary"] == "variant"
