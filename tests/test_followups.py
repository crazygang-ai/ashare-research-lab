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
        "factor_run_universe",
        "ingest-index-members",
        "source 隔离",
    ]

    missing = [keyword for keyword in required_keywords if keyword not in text]
    assert not missing


def test_followups_do_not_keep_phase8_resolved_items_as_open_debt() -> None:
    text = FOLLOWUPS_PATH.read_text(encoding="utf-8")
    stale_phrases = [
        "DuckDB schema 仍未增加物理唯一键",
        "仍未保存完整 universe 快照",
        "仓库没有 GitHub Actions",
        "没有 `.gitkeep`",
        "daily_prices`、`securities`、`trading_calendar` 没有 `source` 字段",
        "历史沪深 300 PIT 成分库尚未落地",
        "AkShare provider 仍是试点薄封装",
        "回测暂不处理 A 股 100 股整数手和零股卖出细节",
    ]

    stale = [phrase for phrase in stale_phrases if phrase in text]
    assert not stale


def test_docs_do_not_reintroduce_resolved_followup_titles() -> None:
    stale_titles = [
        "回测暂不处理 A 股 100 股整数手和零股卖出细节",
    ]

    offenders: list[tuple[str, str]] = []
    for path in (ROOT / "docs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for title in stale_titles:
            if title in text:
                offenders.append((str(path.relative_to(ROOT)), title))

    assert not offenders
