from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ashare.reports.scoring_report import render_scoring_markdown, write_scoring_report
from ashare.scoring.diagnostics import WEIGHT_SENSITIVITY_COLUMNS, YEARLY_STABILITY_COLUMNS
from ashare.scoring.filters import HARD_FILTER_EXCLUSION_COLUMNS
from ashare.scoring.scorer import (
    CompositeScoreResult,
    FACTOR_NORMALIZED_COLUMNS,
    SCORED_CANDIDATE_COLUMNS,
    SCORE_BREAKDOWN_COLUMNS,
)
from ashare.scoring.validation_gate import VALIDATION_GATE_COLUMNS


def _result() -> CompositeScoreResult:
    candidates = pd.DataFrame(
        [[1, "A", "Alpha", "Tech", "Software", "2026-01-02", "run", "LOCAL_FIXTURE", 88.0, 90.0, 80.0, 90.0, 100.0, float("nan"), 2.0, True, "reason", "risk"]],
        columns=SCORED_CANDIDATE_COLUMNS,
    )
    breakdown = pd.DataFrame(
        [["2026-01-02", "run", "LOCAL_FIXTURE", "A", "financial", True, False, 1.0, 80.0, 80.0, 1.0, 0]],
        columns=SCORE_BREAKDOWN_COLUMNS,
    )
    normalized = pd.DataFrame(
        [["2026-01-02", "run", "LOCAL_FIXTURE", "A", "revenue_yoy", "positive", "financial", 0.2, "higher_is_better", 100.0, 1.0, 100.0, "PASS"]],
        columns=FACTOR_NORMALIZED_COLUMNS,
    )
    exclusions = pd.DataFrame(columns=HARD_FILTER_EXCLUSION_COLUMNS)
    gate = pd.DataFrame(
        [["revenue_yoy", "positive", "financial", True, "PASS", "passed", "20", 1.0, 1, 0.1, float("nan"), 1]],
        columns=VALIDATION_GATE_COLUMNS,
    )
    return CompositeScoreResult(
        scored_candidates=candidates,
        score_breakdown=breakdown,
        factor_normalized_scores=normalized,
        hard_filter_exclusions=exclusions,
        validation_gate=gate,
        warnings=("unit warning",),
    )


def _metadata() -> dict[str, object]:
    return {
        "generated_at": "2026-01-02T12:00:00+08:00",
        "db_path": "tmp/ashare.duckdb",
        "as_of_date": "2026-01-02",
        "source_run_id": "run",
        "index_code": "LOCAL_FIXTURE",
        "scoring_config_path": "configs/scoring.yaml",
        "data_dictionary_path": "configs/data_dictionary.yaml",
        "validation_dir": "tmp/validation",
        "config_hash": "abc",
        "top_n": 20,
        "horizons": [20],
        "diagnostics_from": None,
        "diagnostics_to": None,
        "skip_diagnostics": False,
        "enabled_groups": ["financial"],
        "enabled_factors": ["revenue_yoy"],
        "enabled_risk_penalty_factors": [],
        "warnings": ["metadata warning"],
    }


def test_render_scoring_markdown_contains_required_sections_and_caveats() -> None:
    markdown = render_scoring_markdown(
        _result(),
        pd.DataFrame(columns=WEIGHT_SENSITIVITY_COLUMNS),
        pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS),
        _metadata(),
    )

    assert "# Composite Scoring Report" in markdown
    assert "Validation Gate Summary" in markdown
    assert "Hard Filter Exclusion Summary" in markdown
    assert "Top N Composite Score Candidates" in markdown
    assert "Weight Sensitivity Summary" in markdown
    assert "Yearly Stability Summary" in markdown
    assert "composite score is for research only" in markdown
    assert "综合评分仅供研究复盘，不是交易指令" in markdown
    assert "未接入 LLM 事件分" in markdown


def test_write_scoring_report_outputs_all_fixed_artifacts(tmp_path: Path) -> None:
    paths = write_scoring_report(
        _result(),
        tmp_path,
        _metadata(),
        weight_sensitivity=pd.DataFrame(columns=WEIGHT_SENSITIVITY_COLUMNS),
        yearly_stability=pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS),
    )

    expected = {
        "scoring_report.md",
        "scored_candidates.csv",
        "score_breakdown.csv",
        "factor_normalized_scores.csv",
        "hard_filter_exclusions.csv",
        "validation_gate.csv",
        "weight_sensitivity.csv",
        "yearly_stability.csv",
        "score_metadata.json",
    }
    assert {path.name for path in paths.values()} == expected
    assert list(pd.read_csv(tmp_path / "scored_candidates.csv").columns) == SCORED_CANDIDATE_COLUMNS
    assert list(pd.read_csv(tmp_path / "score_breakdown.csv").columns) == SCORE_BREAKDOWN_COLUMNS
    assert list(pd.read_csv(tmp_path / "factor_normalized_scores.csv").columns) == FACTOR_NORMALIZED_COLUMNS

    with pytest.raises(FileExistsError):
        write_scoring_report(_result(), tmp_path, _metadata())
