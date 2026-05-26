from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_DOC = ROOT / "docs/personal_maintenance.md"


def test_personal_maintenance_doc_has_daily_weekly_monthly_and_failure_playbook() -> None:
    text = MAINTENANCE_DOC.read_text(encoding="utf-8")

    required = [
        "scripts/run_hs300_daily_research.sh --as-of",
        "每日运行",
        "每周复核",
        "每月备份",
        "失败定位",
        "永远不提交",
        "DuckDB",
        "cache",
        "data/reports/generated",
        "candidate list is not a trading instruction",
        "composite score is not a trading instruction",
        "backtest is a historical simulation, not a performance promise",
        "stock report is for research review only",
    ]

    missing = [item for item in required if item not in text]
    assert not missing


def test_personal_maintenance_doc_defines_service_and_llm_boundaries() -> None:
    text = MAINTENANCE_DOC.read_text(encoding="utf-8")

    required = [
        "127.0.0.1",
        "read_only: true",
        "不做公网生产部署",
        "不做 RBAC",
        "不做交易接口",
        "真实 LLM 默认不触发",
        "成本预算",
        "证据定位",
        "schema 校验",
    ]

    missing = [item for item in required if item not in text]
    assert not missing


def test_readme_links_personal_maintenance_doc() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/personal_maintenance.md" in text
    assert "每日运行、每周复核、每月备份" in text


def test_ci_covers_install_generated_docs_compile_lint_and_pytest() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    required = [
        "python -m pip install -e .",
        "python docs/build_data_dictionary.py",
        "git diff --exit-code docs/data_dictionary.md docs/factor_definitions.md",
        "python -m compileall -q src/ashare tests",
        "ruff check .",
        "pytest -q",
    ]

    missing = [item for item in required if item not in text]
    assert not missing


def test_gitignore_blocks_generated_research_artifacts() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    required_patterns = [
        "data/raw/",
        "data/processed/",
        "data/snapshots/",
        "data/reports/generated/",
        "data/service/",
        "data/cache/",
        "tests/fixtures/generated/",
        "*.duckdb",
        "*.duckdb.wal",
        "*.duckdb.tmp",
        "configs/watchlist*.csv",
        "configs/watchlist*.txt",
        "!configs/watchlist.example.csv",
    ]

    missing = [pattern for pattern in required_patterns if pattern not in text]
    assert not missing


def test_service_config_stays_local_read_only_and_non_workflow_by_default() -> None:
    config = yaml.safe_load((ROOT / "configs/service.yaml").read_text(encoding="utf-8"))

    assert config["server"]["host"] == "127.0.0.1"
    assert config["database"]["read_only"] is True
    assert config["security"]["allow_http_workflow_run"] is False
    assert config["scheduler"]["enabled"] is False
    assert all(not workflow.get("enabled", False) for workflow in config["workflows"].values())


def test_llm_config_requires_explicit_enablement_before_real_calls() -> None:
    config = yaml.safe_load((ROOT / "configs/llm.yaml").read_text(encoding="utf-8"))

    assert config["enabled"] is False
    assert config["default_llm_mode"] == "fixture"
    assert config["schema_validation"] is True
    assert config["store_evidence"] is True
