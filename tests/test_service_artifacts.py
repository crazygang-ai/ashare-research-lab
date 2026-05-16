from __future__ import annotations

import os
from pathlib import Path

from ashare.service.artifacts import ArtifactRegistry
from ashare.service.config import load_service_config


def _registry(root: Path) -> ArtifactRegistry:
    config = load_service_config(
        "configs/service.yaml",
        overrides={"artifacts": {"roots": [str(root)]}},
    )
    return ArtifactRegistry(config)


def test_artifact_registry_identifies_kinds_and_stable_ids(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    _write_scan(root / "scan", timestamp=1_700_000_000)
    _write_scoring(root / "scoring", generated_at="2026-06-26T18:00:00+08:00")
    _write_backtest(root / "backtest")
    _write_factor_validation(root / "factor-validation")
    _write_event_study(root / "event-study")

    registry = _registry(root)
    records = registry.list_artifacts(limit=20)
    kinds = {record.kind for record in records}

    assert kinds == {"scan", "scoring", "backtest", "factor_validation", "event_study"}
    first_scan = registry.latest("scan")
    second_scan = _registry(root).latest("scan")
    assert first_scan is not None
    assert second_scan is not None
    assert first_scan.artifact_id == second_scan.artifact_id


def test_artifact_registry_sorting_and_missing_file_warning(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    old_scan = root / "old-scan"
    new_scan = root / "new-scan"
    _write_scan(old_scan, timestamp=1_700_000_000)
    _write_scan(new_scan, timestamp=1_800_000_000)
    (root / "partial-scan").mkdir(parents=True)
    (root / "partial-scan" / "candidate_list.md").write_text("# partial\n", encoding="utf-8")

    registry = _registry(root)
    latest = registry.latest("scan")
    partial = [
        record for record in registry.list_artifacts(kind="scan") if "partial-scan" in record.output_dir_display
    ][0]

    assert latest is not None
    assert latest.output_dir.name == "new-scan"
    assert any("candidates.csv" in warning for warning in partial.warnings)


def test_artifact_registry_rejects_path_like_artifact_id(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "reports")

    assert registry.get("../candidate_list.md") is None


def _write_scan(path: Path, timestamp: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "candidates.csv").write_text("stock_code,rank\n000001.SZ,1\n", encoding="utf-8")
    (path / "candidate_list.md").write_text("# Candidate List\n", encoding="utf-8")
    os.utime(path / "candidates.csv", (timestamp, timestamp))
    os.utime(path / "candidate_list.md", (timestamp, timestamp))


def _write_scoring(path: Path, generated_at: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "scoring_report.md").write_text("# Scoring\n", encoding="utf-8")
    (path / "scored_candidates.csv").write_text("stock_code,rank,total_score\n000001.SZ,1,99\n", encoding="utf-8")
    (path / "score_metadata.json").write_text(
        f'{{"generated_at": "{generated_at}", "title": "Score <unsafe>"}}\n',
        encoding="utf-8",
    )


def _write_backtest(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "backtest_report.md").write_text("# Backtest\n", encoding="utf-8")
    (path / "metrics.csv").write_text("total_return,max_drawdown\n0.1,-0.2\n", encoding="utf-8")
    (path / "equity_curve.csv").write_text("trade_date,nav\n2026-01-01,1.0\n", encoding="utf-8")


def _write_factor_validation(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "factor_validation_report.md").write_text("# Validation\n", encoding="utf-8")
    (path / "coverage.csv").write_text("factor_name,coverage\nreturn_20d,1\n", encoding="utf-8")
    (path / "rank_ic.csv").write_text("factor_name,horizon,rank_ic\nreturn_20d,20,0.1\n", encoding="utf-8")
    (path / "ic_summary.csv").write_text("factor_name,horizon,icir\nreturn_20d,20,1.2\n", encoding="utf-8")


def _write_event_study(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "event_study_report.md").write_text("# Event Study\n", encoding="utf-8")
    (path / "event_samples.csv").write_text(
        "event_id,stock_code,event_type\nann-1,000001.SZ,earnings_forecast\n",
        encoding="utf-8",
    )
    (path / "event_window_returns.csv").write_text(
        "event_id,horizon,event_return\nann-1,5,0.1\n",
        encoding="utf-8",
    )
    (path / "event_summary.csv").write_text(
        "event_type,horizon,sample_count\nearnings_forecast,5,1\n",
        encoding="utf-8",
    )
