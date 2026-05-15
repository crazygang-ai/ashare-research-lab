"""Markdown, CSV, and JSON reports for Phase 3 composite scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import json
from pathlib import Path

import pandas as pd

from ashare.scoring.diagnostics import WEIGHT_SENSITIVITY_COLUMNS, YEARLY_STABILITY_COLUMNS
from ashare.scoring.filters import HARD_FILTER_EXCLUSION_COLUMNS
from ashare.scoring.scorer import (
    CompositeScoreResult,
    FACTOR_NORMALIZED_COLUMNS,
    SCORED_CANDIDATE_COLUMNS,
    SCORE_BREAKDOWN_COLUMNS,
)
from ashare.scoring.validation_gate import VALIDATION_GATE_COLUMNS


SCORING_REPORT_FILES = {
    "markdown": "scoring_report.md",
    "scored_candidates": "scored_candidates.csv",
    "score_breakdown": "score_breakdown.csv",
    "factor_normalized_scores": "factor_normalized_scores.csv",
    "hard_filter_exclusions": "hard_filter_exclusions.csv",
    "validation_gate": "validation_gate.csv",
    "weight_sensitivity": "weight_sensitivity.csv",
    "yearly_stability": "yearly_stability.csv",
    "metadata": "score_metadata.json",
}

REQUIRED_SCORING_METADATA = {
    "generated_at",
    "db_path",
    "as_of_date",
    "source_run_id",
    "index_code",
    "scoring_config_path",
    "data_dictionary_path",
    "validation_dir",
    "config_hash",
    "top_n",
    "horizons",
    "diagnostics_from",
    "diagnostics_to",
    "skip_diagnostics",
    "enabled_groups",
    "enabled_factors",
    "enabled_risk_penalty_factors",
    "warnings",
}


def render_scoring_markdown(
    result: CompositeScoreResult,
    weight_sensitivity: pd.DataFrame,
    yearly_stability: pd.DataFrame,
    metadata: Mapping[str, object],
) -> str:
    """Render a deterministic Markdown scoring report without file I/O."""
    _require_metadata(metadata)
    candidates = _ordered(result.scored_candidates, SCORED_CANDIDATE_COLUMNS, ["rank"])
    validation_gate = _ordered(
        result.validation_gate,
        VALIDATION_GATE_COLUMNS,
        ["score_role", "score_group", "factor_name"],
    )
    exclusions = _ordered(
        result.hard_filter_exclusions,
        HARD_FILTER_EXCLUSION_COLUMNS,
        ["stock_code", "hard_filter_name"],
    )
    sensitivity = _ordered(
        weight_sensitivity,
        WEIGHT_SENSITIVITY_COLUMNS,
        ["scenario_type", "changed_key", "change_direction"],
    )
    stability = _ordered(yearly_stability, YEARLY_STABILITY_COLUMNS, ["year", "horizon"])

    lines: list[str] = [
        "# Composite Scoring Report",
        "",
        "## Metadata",
        "",
        f"- generated_at: {_stringify(metadata['generated_at'])}",
        f"- db_path: {_stringify(metadata['db_path'])}",
        f"- as_of_date: {_stringify(metadata['as_of_date'])}",
        f"- source_run_id: {_stringify(metadata['source_run_id'])}",
        f"- index_code: {_stringify(metadata['index_code'])}",
        f"- scoring_config_path: {_stringify(metadata['scoring_config_path'])}",
        f"- data_dictionary_path: {_stringify(metadata['data_dictionary_path'])}",
        f"- validation_dir: {_stringify(metadata['validation_dir'])}",
        f"- config_hash: {_stringify(metadata['config_hash'])}",
        f"- top_n: {_stringify(metadata['top_n'])}",
        f"- horizons: {_format_sequence(metadata['horizons'])}",
        f"- diagnostics_from: {_stringify(metadata['diagnostics_from'])}",
        f"- diagnostics_to: {_stringify(metadata['diagnostics_to'])}",
        f"- skip_diagnostics: {_stringify(metadata['skip_diagnostics'])}",
        "",
        "## Enabled Scoring Configuration",
        "",
        f"- enabled_groups: {_format_sequence(metadata['enabled_groups'])}",
        f"- enabled_factors: {_format_sequence(metadata['enabled_factors'])}",
        f"- enabled_risk_penalty_factors: "
        f"{_format_sequence(metadata['enabled_risk_penalty_factors'])}",
        "",
        "## Validation Gate Summary",
        "",
        _validation_summary(validation_gate),
        "",
        _markdown_table(validation_gate),
        "",
        "## Hard Filter Exclusion Summary",
        "",
        _hard_filter_summary(exclusions),
        "",
        _markdown_table(exclusions),
        "",
        "## Top N Composite Score Candidates",
        "",
        _markdown_table(candidates),
        "",
        "## Candidate Score Details",
        "",
        _markdown_table(
            candidates.loc[
                :,
                [
                    column
                    for column in [
                        "rank",
                        "stock_code",
                        "financial_score",
                        "valuation_score",
                        "momentum_score",
                        "event_score",
                        "risk_penalty",
                        "total_score",
                    ]
                    if column in candidates.columns
                ],
            ]
        ),
        "",
        "## Weight Sensitivity Summary",
        "",
        _markdown_table(sensitivity),
        "",
        "## Yearly Stability Summary",
        "",
        _markdown_table(stability),
        "",
        "## Warnings",
        "",
    ]
    warnings = list(result.warnings) + [str(item) for item in metadata.get("warnings", [])]
    warnings = list(dict.fromkeys(item for item in warnings if item))
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## Methodology Notes",
            "",
            "- composite score is for research only and is not a trading instruction.",
            "- 综合评分仅供研究复盘，不是交易指令。",
            "- `score` 不替代 Phase 1a-6 的 `scan`；`scan` 是单因子候选清单，"
            "`score` 是多因子综合评分报告。",
            "- 只有通过验证门槛的因子进入总分。",
            "- hard filters 不参与连续打分。",
            "- soft risk penalty 是扣分项，不是交易卖出信号。",
            "- 本报告不是组合回测报告。",
            "- 本报告未接入 LLM 事件分。",
            "- 本报告不包含事件研究。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_scoring_report(
    result: CompositeScoreResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    weight_sensitivity: pd.DataFrame | None = None,
    yearly_stability: pd.DataFrame | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write scoring report artifacts to ``output_dir`` only."""
    _require_metadata(metadata)
    resolved = Path(output_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    paths = {key: resolved / filename for key, filename in SCORING_REPORT_FILES.items()}
    _fail_if_exists(paths.values(), overwrite=overwrite)

    sensitivity = (
        weight_sensitivity.copy()
        if weight_sensitivity is not None
        else pd.DataFrame(columns=WEIGHT_SENSITIVITY_COLUMNS)
    )
    stability = (
        yearly_stability.copy()
        if yearly_stability is not None
        else pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS)
    )

    _ordered(result.scored_candidates, SCORED_CANDIDATE_COLUMNS, ["rank"]).to_csv(
        paths["scored_candidates"],
        index=False,
    )
    _ordered(result.score_breakdown, SCORE_BREAKDOWN_COLUMNS, ["stock_code", "score_group"]).to_csv(
        paths["score_breakdown"],
        index=False,
    )
    _ordered(
        result.factor_normalized_scores,
        FACTOR_NORMALIZED_COLUMNS,
        ["stock_code", "score_group", "factor_name"],
    ).to_csv(paths["factor_normalized_scores"], index=False)
    _ordered(
        result.hard_filter_exclusions,
        HARD_FILTER_EXCLUSION_COLUMNS,
        ["stock_code", "hard_filter_name"],
    ).to_csv(paths["hard_filter_exclusions"], index=False)
    _ordered(
        result.validation_gate,
        VALIDATION_GATE_COLUMNS,
        ["score_role", "score_group", "factor_name"],
    ).to_csv(paths["validation_gate"], index=False)
    _ordered(
        sensitivity,
        WEIGHT_SENSITIVITY_COLUMNS,
        ["scenario_type", "changed_key", "change_direction"],
    ).to_csv(paths["weight_sensitivity"], index=False)
    _ordered(stability, YEARLY_STABILITY_COLUMNS, ["year", "horizon"]).to_csv(
        paths["yearly_stability"],
        index=False,
    )
    paths["metadata"].write_text(
        json.dumps(_jsonable(metadata), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(
        render_scoring_markdown(result, sensitivity, stability, metadata),
        encoding="utf-8",
    )
    return paths


def write_validation_failure_artifacts(
    validation_gate: pd.DataFrame,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write strict-mode validation failure artifacts required before fail-fast."""
    resolved = Path(output_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    paths = {
        "validation_gate": resolved / SCORING_REPORT_FILES["validation_gate"],
        "metadata": resolved / SCORING_REPORT_FILES["metadata"],
    }
    _fail_if_exists(paths.values(), overwrite=overwrite)
    _ordered(validation_gate, VALIDATION_GATE_COLUMNS, ["score_role", "score_group", "factor_name"]).to_csv(
        paths["validation_gate"],
        index=False,
    )
    paths["metadata"].write_text(
        json.dumps(_jsonable(metadata), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths


def _ordered(frame: pd.DataFrame, columns: Sequence[str], sort_keys: Sequence[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, list(columns)]
    keys = [key for key in sort_keys if key in result.columns]
    if keys and not result.empty:
        result = result.sort_values(keys, kind="mergesort")
    return result.reset_index(drop=True)


def _validation_summary(validation_gate: pd.DataFrame) -> str:
    if validation_gate.empty:
        return "- validation_gate rows: 0"
    counts = validation_gate["validation_status"].value_counts(dropna=False).to_dict()
    return "\n".join(f"- {status}: {count}" for status, count in sorted(counts.items()))


def _hard_filter_summary(exclusions: pd.DataFrame) -> str:
    if exclusions.empty:
        return "- hard_filter_exclusions: 0"
    counts = exclusions["hard_filter_name"].value_counts(dropna=False).to_dict()
    return "\n".join(f"- {name}: {count}" for name, count in sorted(counts.items()))


def _require_metadata(metadata: Mapping[str, object]) -> None:
    missing = sorted(REQUIRED_SCORING_METADATA.difference(metadata.keys()))
    if missing:
        raise ValueError(f"Missing required metadata for scoring report: {', '.join(missing)}")


def _fail_if_exists(paths: Sequence[Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing report file(s): " + ", ".join(existing)
        )


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    if not columns:
        return "_No columns._"
    header = "| " + " | ".join(_escape_markdown_cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| "
        + " | ".join(_escape_markdown_cell(_stringify(value)) for value in row)
        + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    if not rows:
        rows = ["| " + " | ".join("" for _ in columns) + " |"]
    return "\n".join([header, separator, *rows])


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_sequence(value: object) -> str:
    if isinstance(value, (str, bytes)):
        return str(value)
    try:
        return ", ".join(_stringify(item) for item in value)  # type: ignore[union-attr]
    except TypeError:
        return _stringify(value)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
