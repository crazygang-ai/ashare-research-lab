from __future__ import annotations

from pathlib import Path
import subprocess

import yaml


SCRIPT = Path("scripts/run_hs300_daily_research.sh")
SCORING_CONFIG = Path("configs/scoring_hs300_daily_exploratory.yaml")


def test_hs300_daily_research_script_requires_explicit_as_of() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ASOF is required" in result.stderr
    assert "today" not in result.stdout.lower()


def test_hs300_daily_research_script_dry_run_uses_fixed_names_and_full_chain() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--as-of", "2026-05-22", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout = result.stdout
    assert "DB=data/processed/hs300_daily.duckdb" in stdout
    assert "SOURCE=akshare-hs300-daily" in stdout
    assert "ASOF=2026-05-22" in stdout
    assert "FACTOR_RUN=hs300-factor-20260522" in stdout
    assert "VALIDATION_RUN=hs300-factor-validation-20260522" in stdout
    assert "SCAN_RUN=hs300-scan-20260522" in stdout
    assert "SCORE_RUN=hs300-score-20260522" in stdout
    assert "STOCK_CODE=002594.SZ" in stdout
    assert "--scoring-config configs/scoring_hs300_daily_exploratory.yaml" in stdout

    for command in [
        "ashare ingest",
        "ashare as-of",
        "ashare calculate-factors",
        "ashare report --kind factor-validation",
        "ashare scan",
        "ashare score",
        "ashare stock-report",
    ]:
        assert command in stdout

    for research_disclaimer in [
        "candidate list is not a trading instruction",
        "composite score is not a trading instruction",
        "factor validation forward return is a statistical label",
        "stock report is for research review only",
    ]:
        assert research_disclaimer in stdout


def test_readme_documents_daily_hs300_research_workflow() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## 每日 HS300 个人研究链路" in readme
    assert "scripts/run_hs300_daily_research.sh --as-of 2026-05-22" in readme
    assert "DB=data/processed/hs300_daily.duckdb" in readme
    assert "SOURCE=akshare-hs300-daily" in readme
    assert "FACTOR_RUN=hs300-factor-${ASOF_NODASH}" in readme
    assert "VALIDATION_RUN=hs300-factor-validation-${ASOF_NODASH}" in readme
    assert "SCAN_RUN=hs300-scan-${ASOF_NODASH}" in readme
    assert "SCORE_RUN=hs300-score-${ASOF_NODASH}" in readme
    assert "AkShare 指数成分是当前快照，不是严格历史 PIT 成分库" in readme
    assert "factor validation forward return is a statistical label" in readme
    assert "configs/scoring_hs300_daily_exploratory.yaml" in readme


def test_hs300_daily_scoring_config_is_exploratory_and_loadable() -> None:
    config = yaml.safe_load(SCORING_CONFIG.read_text(encoding="utf-8"))

    assert config["version"] == "hs300_daily_exploratory.v1"
    assert config["validation_gate"]["mode"] == "non_strict"
    assert config["validation_gate"]["min_coverage"] == 0.2
    assert config["validation_gate"]["min_valid_oriented_ic_dates"] == 1
    assert config["validation_gate"]["min_mean_oriented_rank_ic"] == -999.0
    assert config["validation_gate"]["min_oriented_icir"] == -999.0
