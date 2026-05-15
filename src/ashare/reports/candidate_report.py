"""Markdown and CSV reports for Phase 1a-6 candidate scans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ashare.scan.candidates import CandidateScanResult, candidate_columns


CANDIDATE_REPORT_FILES = {
    "markdown": "candidate_list.md",
    "csv": "candidates.csv",
}

REQUIRED_CANDIDATE_METADATA = {
    "generated_at",
    "db_path",
    "source_run_id",
    "as_of_date",
    "sort_factor",
    "sort_factor_direction",
    "top_n",
    "factor_names",
    "hard_filter_names",
    "data_dictionary_path",
}


def render_candidate_markdown(
    result: CandidateScanResult,
    metadata: Mapping[str, object],
) -> str:
    """Render a deterministic Markdown candidate report without file I/O."""
    _require_metadata(metadata, REQUIRED_CANDIDATE_METADATA, "candidate report")
    candidates = _ordered_candidates(result.candidates, metadata["factor_names"])  # type: ignore[arg-type]

    lines: list[str] = [
        "# Candidate List",
        "",
        "## Metadata",
        "",
        f"- generated_at: {_stringify(metadata['generated_at'])}",
        f"- db_path: {_stringify(metadata['db_path'])}",
        f"- as_of_date: {_stringify(metadata['as_of_date'])}",
        f"- source_run_id: {_stringify(metadata['source_run_id'])}",
        f"- sort_factor: {_stringify(metadata['sort_factor'])}",
        f"- sort_factor_direction: {_stringify(metadata['sort_factor_direction'])}",
        f"- top_n: {_stringify(metadata['top_n'])}",
        f"- factor_names: {_format_sequence(metadata['factor_names'])}",
        f"- hard_filter_names: {_format_sequence(metadata['hard_filter_names'])}",
        f"- data_dictionary_path: {_stringify(metadata['data_dictionary_path'])}",
        "",
        "## Candidates",
        "",
        _markdown_table(candidates),
        "",
        "## Factor Details",
        "",
        "- 因子分项列使用 `factor__<factor_name>` 命名。",
        "- 硬过滤列固定为 `hard_filter__is_st`, `hard_filter__is_suspended`, "
        "`hard_filter__is_delisted`, `hard_filter__low_liquidity`。",
        "",
        "## Selection Reason And Risk Tips",
        "",
        _markdown_table(
            candidates.loc[
                :,
                [
                    column
                    for column in ["rank", "stock_code", "selection_reason", "risk_tips"]
                    if column in candidates.columns
                ],
            ]
        ),
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
            "- candidate list is for research only and is not a trading instruction.",
            "- 候选清单未做综合评分。",
            "- 候选清单未做组合回测。",
            "- 候选清单未应用真实交易约束。",
            "- 候选清单未接入 LLM。",
            "- 排序只使用显式传入的 `sort_factor`。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_candidate_report(
    result: CandidateScanResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write candidate Markdown and CSV files."""
    _require_metadata(metadata, REQUIRED_CANDIDATE_METADATA, "candidate report")
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        key: resolved_output_dir / filename for key, filename in CANDIDATE_REPORT_FILES.items()
    }
    _fail_if_exists(paths.values(), overwrite=overwrite)

    candidates = _ordered_candidates(result.candidates, metadata["factor_names"])  # type: ignore[arg-type]
    candidates.to_csv(paths["csv"], index=False)
    paths["markdown"].write_text(render_candidate_markdown(result, metadata), encoding="utf-8")
    return paths


def _ordered_candidates(candidates: pd.DataFrame, factor_names: object) -> pd.DataFrame:
    names = tuple(str(name) for name in factor_names)  # type: ignore[union-attr]
    columns = candidate_columns(names)
    result = candidates.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, columns]
    if "rank" in result.columns and not result.empty:
        result = result.sort_values("rank", kind="mergesort")
    return result.reset_index(drop=True)


def _require_metadata(
    metadata: Mapping[str, object],
    required_keys: set[str],
    context: str,
) -> None:
    missing = sorted(required_keys.difference(metadata.keys()))
    if missing:
        raise ValueError(f"Missing required metadata for {context}: {', '.join(missing)}")


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
