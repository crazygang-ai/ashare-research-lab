"""Markdown and CSV reports for Phase 1a-5 factor validation results."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.validation.runner import FactorValidationResult


FACTOR_REPORT_FILES = {
    "markdown": "factor_validation_report.md",
    "coverage": "coverage.csv",
    "label_summary": "label_summary.csv",
    "rank_ic": "rank_ic.csv",
    "ic_summary": "ic_summary.csv",
    "group_returns": "group_returns.csv",
    "decay_curve": "decay_curve.csv",
    "yearly_ic_summary": "yearly_ic_summary.csv",
}

REQUIRED_FACTOR_METADATA = {
    "generated_at",
    "db_path",
    "source_run_id",
    "validation_from",
    "validation_to",
    "factors",
    "horizons",
    "n_groups",
    "include_hard_filters",
    "validation_config_path",
    "data_dictionary_path",
}

_SORT_KEYS = {
    "coverage": ("factor_name", "trade_date"),
    "label_summary": ("horizon", "trade_date"),
    "rank_ic": ("factor_name", "horizon", "trade_date"),
    "ic_summary": ("factor_name", "horizon"),
    "group_returns": ("factor_name", "horizon", "trade_date"),
    "decay_curve": ("factor_name", "horizon"),
    "yearly_ic_summary": ("factor_name", "horizon", "year"),
}


def render_factor_validation_markdown(
    result: FactorValidationResult,
    metadata: Mapping[str, object],
) -> str:
    """Render a deterministic Markdown report without reading or writing files."""
    _require_metadata(metadata, REQUIRED_FACTOR_METADATA, "factor validation report")

    sorted_frames = _sorted_factor_frames(result)
    lines: list[str] = [
        "# Factor Validation Report",
        "",
        "## Metadata",
        "",
        f"- generated_at: {_stringify(metadata['generated_at'])}",
        f"- db_path: {_stringify(metadata['db_path'])}",
        f"- validation_from: {_stringify(metadata['validation_from'])}",
        f"- validation_to: {_stringify(metadata['validation_to'])}",
        f"- source_run_id: {_stringify(metadata['source_run_id'])}",
        f"- factors: {_format_sequence(metadata['factors'])}",
        f"- horizons: {_format_sequence(metadata['horizons'])}",
        f"- n_groups: {_stringify(metadata['n_groups'])}",
        f"- include_hard_filters: {_stringify(metadata['include_hard_filters'])}",
        f"- validation_config_path: {_stringify(metadata['validation_config_path'])}",
        f"- data_dictionary_path: {_stringify(metadata['data_dictionary_path'])}",
        "",
        "## Label Summary",
        "",
        _markdown_table(sorted_frames["label_summary"]),
        "",
        "## Coverage And Missing Rate",
        "",
        _markdown_table(sorted_frames["coverage"]),
        "",
        "## Rank IC Detail",
        "",
        _markdown_table(sorted_frames["rank_ic"]),
        "",
        "## Rank IC And ICIR Summary",
        "",
        _markdown_table(sorted_frames["ic_summary"]),
        "",
        "## Top And Bottom Group Returns",
        "",
        _markdown_table(sorted_frames["group_returns"]),
        "",
        "## Decay Curve",
        "",
        _markdown_table(sorted_frames["decay_curve"]),
        "",
        "## Yearly IC Stability",
        "",
        _markdown_table(sorted_frames["yearly_ic_summary"]),
        "",
        "## Warnings",
        "",
    ]

    if result.warnings:
        for warning in result.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## Methodology Notes",
            "",
            "- forward return 是验证标签，不是交易收益。",
            "- long_short_return 只用于单因子分析，不代表可执行策略。",
            "- yearly_ic_summary 按自然年切片观察 IC 稳定性，不代表年度收益承诺。",
            "- 本报告不是回测报告。",
            "- 本报告不包含综合评分。",
            "- 分行业验证表现不在 Phase 1a-6 输出范围内。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_factor_validation_report(
    result: FactorValidationResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write the factor validation Markdown and full-detail CSV files."""
    _require_metadata(metadata, REQUIRED_FACTOR_METADATA, "factor validation report")
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    paths = {key: resolved_output_dir / filename for key, filename in FACTOR_REPORT_FILES.items()}
    _fail_if_exists(paths.values(), overwrite=overwrite)

    sorted_frames = _sorted_factor_frames(result)
    paths["markdown"].write_text(
        render_factor_validation_markdown(result, metadata),
        encoding="utf-8",
    )
    for key in [
        "coverage",
        "label_summary",
        "rank_ic",
        "ic_summary",
        "group_returns",
        "decay_curve",
        "yearly_ic_summary",
    ]:
        sorted_frames[key].to_csv(paths[key], index=False)
    return paths


def _sorted_factor_frames(result: FactorValidationResult) -> dict[str, pd.DataFrame]:
    return {
        "coverage": _sort_frame(result.coverage, "coverage"),
        "label_summary": _sort_frame(result.label_summary, "label_summary"),
        "rank_ic": _sort_frame(result.rank_ic, "rank_ic"),
        "ic_summary": _sort_frame(result.ic_summary, "ic_summary"),
        "group_returns": _sort_frame(result.group_returns, "group_returns"),
        "decay_curve": _sort_frame(result.decay_curve, "decay_curve"),
        "yearly_ic_summary": _sort_frame(result.yearly_ic_summary, "yearly_ic_summary"),
    }


def _sort_frame(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    result = frame.copy()
    sort_keys = [key for key in _SORT_KEYS[name] if key in result.columns]
    if name == "label_summary" and "trade_date" not in result.columns:
        sort_keys = [key for key in ("horizon",) if key in result.columns]
    if sort_keys:
        result = result.sort_values(sort_keys, kind="mergesort")
    return result.reset_index(drop=True)


def _require_metadata(
    metadata: Mapping[str, object],
    required_keys: set[str],
    context: str,
) -> None:
    missing = sorted(required_keys.difference(metadata.keys()))
    if missing:
        raise ValueError(f"Missing required metadata for {context}: {', '.join(missing)}")


def _fail_if_exists(paths: Any, overwrite: bool) -> None:
    if overwrite:
        return
    existing = [str(path) for path in paths if Path(path).exists()]
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
        "| " + " | ".join(_escape_markdown_cell(_stringify(value)) for value in row) + " |"
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
