from __future__ import annotations

import os
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


def test_hs300_daily_research_script_prints_completion_summary(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_conda = fake_bin / "conda"
    fake_conda.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" != "run" ]]; then
  echo "expected conda run" >&2
  exit 2
fi
shift 3
if [[ "$1" != "ashare" ]]; then
  echo "expected ashare command" >&2
  exit 2
fi
command="$2"
shift 2

value_for() {
  local name="$1"
  shift
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "$name" ]]; then
      echo "$2"
      return 0
    fi
    shift
  done
  return 1
}

case "$command" in
  ingest)
    output_dir="$(value_for --quality-report-dir "$@")"
    mkdir -p "$output_dir"
    printf '# Data Quality\\n' > "$output_dir/data_quality_report.md"
    printf 'dataset,row_count\\ntrading_calendar,10\\ndaily_prices,20\\n' > "$output_dir/dataset_summary.csv"
    ;;
  as-of|calculate-factors)
    ;;
  report)
    output_dir="$(value_for --output-dir "$@")"
    mkdir -p "$output_dir"
    printf '# Factor Validation\\n' > "$output_dir/factor_validation_report.md"
    printf 'factor_name,horizon\\nreturn_20d,20\\n' > "$output_dir/ic_summary.csv"
    printf '{"run_id":"validation"}\\n' > "$output_dir/run_manifest.json"
    ;;
  scan)
    output_dir="$(value_for --output-dir "$@")"
    mkdir -p "$output_dir"
    printf 'rank,stock_code\\n1,002594.SZ\\n2,000001.SZ\\n' > "$output_dir/candidates.csv"
    printf '{"run_id":"scan"}\\n' > "$output_dir/run_manifest.json"
    ;;
  score)
    output_dir="$(value_for --output-dir "$@")"
    mkdir -p "$output_dir"
    printf 'rank,stock_code,total_score\\n1,002594.SZ,90\\n' > "$output_dir/scored_candidates.csv"
    printf '{"run_id":"score"}\\n' > "$output_dir/run_manifest.json"
    ;;
  stock-report)
    output_dir="$(value_for --output-dir "$@")"
    mkdir -p "$output_dir"
    printf '# Stock Report\\n002594.SZ\\n' > "$output_dir/stock_report.md"
    printf '{"run_id":"stock"}\\n' > "$output_dir/run_manifest.json"
    ;;
  *)
    echo "unknown ashare command: $command" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_conda.chmod(0o755)

    report_root = tmp_path / "reports"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "DB": str(tmp_path / "hs300.duckdb"),
        "CACHE_DIR": str(tmp_path / "cache"),
        "REPORT_ROOT": str(report_root),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--as-of", "2026-05-22"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    run_root = report_root / "20260522"
    stdout = result.stdout
    assert "Run summary:" in stdout
    assert f"data_quality_report: {run_root / 'data-quality/data_quality_report.md'}" in stdout
    assert f"factor_validation_report: {run_root / 'factor-validation/factor_validation_report.md'}" in stdout
    assert f"stock_report: {run_root / 'stock-002594-SZ/stock_report.md'}" in stdout
    assert "candidates.csv rows: 2" in stdout
    assert "scored_candidates.csv rows: 1" in stdout
    assert "target_in_scan: yes" in stdout
    assert "target_in_score: yes" in stdout
    assert "target_in_stock_report: yes" in stdout


def test_hs300_daily_research_script_includes_target_when_max_symbols_is_used() -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--as-of",
            "2026-05-22",
            "--max-symbols",
            "20",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--max-symbols 20 --include-symbol 002594.SZ" in result.stdout
