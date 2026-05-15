from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOLLOWUPS_PATH = ROOT / "docs/planning/followups.md"


def test_followups_file_exists_and_is_not_empty() -> None:
    assert FOLLOWUPS_PATH.exists()
    assert FOLLOWUPS_PATH.read_text(encoding="utf-8").strip()


def test_followups_contains_priority_sections() -> None:
    text = FOLLOWUPS_PATH.read_text(encoding="utf-8")

    assert re.search(r"^##\s+高优先", text, re.MULTILINE)
    assert re.search(r"^##\s+中优先", text, re.MULTILINE)
    assert re.search(r"^##\s+低优先", text, re.MULTILINE)


def test_followup_entries_record_context_triggers_or_decisions() -> None:
    text = FOLLOWUPS_PATH.read_text(encoding="utf-8")
    entries = re.findall(r"^###\s+D\d+\..*?(?=^###\s+D\d+\.|\Z)", text, re.MULTILINE | re.DOTALL)

    assert entries
    for entry in entries:
        keyword_count = sum(keyword in entry for keyword in ("现状", "触发", "决策"))
        assert keyword_count >= 2


def test_followups_cover_required_debt_items() -> None:
    text = FOLLOWUPS_PATH.read_text(encoding="utf-8")
    required_keywords = [
        "effective_date",
        "盘前",
        "盘中",
        "盘后",
        "factor_values",
        "PRIMARY KEY",
        "schema_version",
        "迁移序列",
        "演进",
        "ingest_local",
        "清表",
        "真实数据",
        "JSON extension",
        "fail-fast",
        "is_suspended",
        "data_missing",
        "test_asof",
        "硬编码",
        "pre-commit",
        "lint hook",
        "data/raw",
        ".gitkeep",
    ]

    missing = [keyword for keyword in required_keywords if keyword not in text]
    assert not missing
