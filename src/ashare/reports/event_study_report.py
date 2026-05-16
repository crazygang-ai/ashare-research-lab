"""Markdown and CSV reports for Phase 6 event-study validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ashare.validation.event_study import (
    EVENT_SAMPLE_COLUMNS,
    EVENT_SUMMARY_COLUMNS,
    EVENT_WINDOW_RETURN_COLUMNS,
    EventStudyResult,
)


EVENT_STUDY_REPORT_FILES = {
    "markdown": "event_study_report.md",
    "event_samples": "event_samples.csv",
    "event_window_returns": "event_window_returns.csv",
    "event_summary": "event_summary.csv",
}

REQUIRED_EVENT_STUDY_METADATA = {
    "generated_at",
    "db_path",
    "event_source",
    "event_types",
    "start_date",
    "end_date",
    "horizons",
    "index_code",
    "benchmark",
    "deduplicate",
    "min_confidence",
}


def render_event_study_markdown(
    result: EventStudyResult,
    metadata: Mapping[str, object],
) -> str:
    """Render a deterministic Markdown event-study report."""
    _require_metadata(metadata, REQUIRED_EVENT_STUDY_METADATA, "event study report")
    samples = _ordered(result.event_samples, EVENT_SAMPLE_COLUMNS, ["effective_date", "event_id"])
    summary = _ordered(
        result.event_summary,
        EVENT_SUMMARY_COLUMNS,
        ["event_source", "event_type", "horizon"],
    )
    total_samples = len(samples)
    included_samples = int(samples["included"].astype(bool).sum()) if "included" in samples else 0
    skipped_samples = total_samples - included_samples
    skip_summary = _skip_summary(samples)
    duplicate_group_count = (
        int(samples.loc[samples["duplicate_group_id"] != "", "duplicate_group_id"].nunique())
        if "duplicate_group_id" in samples and not samples.empty
        else 0
    )
    duplicate_row_count = (
        int((samples["duplicate_group_id"] != "").sum())
        if "duplicate_group_id" in samples and not samples.empty
        else 0
    )
    benchmark = str(metadata["benchmark"])
    benchmark_note = (
        "当前基准为合成等权 PIT universe 基准。"
        if benchmark == "synthetic_equal_weight"
        else "当前基准为合成市值加权 PIT universe 基准。"
        if benchmark == "synthetic_cap_weight"
        else "当前报告不使用基准，超额收益字段为空。"
    )
    small_sample_note = _small_sample_note(summary)

    lines = [
        "# Event Study Report",
        "",
        "## Scope",
        "",
        "- 本报告是事件研究，不是组合回测。",
        "- 本报告不是交易指令，不包含买入、卖出或目标价建议。",
        "- event_return 是事件后 close-to-close 统计收益，不代表可执行交易收益。",
        "",
        "## Metadata",
        "",
        f"- generated_at: {_stringify(metadata['generated_at'])}",
        f"- db_path: {_stringify(metadata['db_path'])}",
        f"- event_source: {_stringify(metadata['event_source'])}",
        f"- event_types: {_format_sequence(metadata['event_types'])}",
        f"- event interval: {_stringify(metadata['start_date'])} to {_stringify(metadata['end_date'])}",
        f"- horizons: {_format_sequence(metadata['horizons'])}",
        f"- index_code: {_stringify(metadata['index_code'])}",
        f"- benchmark: {_stringify(metadata['benchmark'])}",
        f"- deduplicate: {_stringify(metadata['deduplicate'])}",
        f"- min_confidence: {_stringify(metadata['min_confidence'])}",
        "",
        "## PIT Methodology",
        "",
        "- 事件样本严格使用 `effective_date BETWEEN --from AND --to`。",
        "- 事件窗口从 `effective_date` 当天收盘后开始观察，使用 `event_date_close -> future_close`。",
        "- 收益价格使用 `adjusted_close = close * adj_factor`，`adj_factor` 为空时回退到 `close`。",
        "- 合成基准使用事件日 `as_of_date = event_date` 的 PIT `universe_members`。",
        f"- {benchmark_note}",
        "",
        "## Sample Counts",
        "",
        f"- total_event_samples: {total_samples}",
        f"- included_event_samples: {included_samples}",
        f"- skipped_event_samples: {skipped_samples}",
        f"- duplicate_group_count: {duplicate_group_count}",
        f"- duplicate_row_count: {duplicate_row_count}",
        f"- deduplication_mode: {_stringify(metadata['deduplicate'])}",
        "",
        "## Skip Reasons",
        "",
        _markdown_table(skip_summary),
        "",
        "## Horizon Summary",
        "",
        _markdown_table(summary),
        "",
        "## Sample Risk",
        "",
        f"- {small_sample_note}",
        "- 重复事件样本会影响统计独立性，报告已披露重复组和重复行数量。",
        "",
        "## Warnings",
        "",
    ]
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- (none)")
    return "\n".join(lines).rstrip() + "\n"


def write_event_study_report(
    result: EventStudyResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write event-study Markdown and CSV artifacts."""
    _require_metadata(metadata, REQUIRED_EVENT_STUDY_METADATA, "event study report")
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        key: resolved_output_dir / filename
        for key, filename in EVENT_STUDY_REPORT_FILES.items()
    }
    _fail_if_exists(paths.values(), overwrite=overwrite)

    _ordered(result.event_samples, EVENT_SAMPLE_COLUMNS, ["effective_date", "event_id"]).to_csv(
        paths["event_samples"],
        index=False,
    )
    _ordered(
        result.event_window_returns,
        EVENT_WINDOW_RETURN_COLUMNS,
        ["event_date", "event_type", "stock_code", "event_id", "horizon"],
    ).to_csv(paths["event_window_returns"], index=False)
    _ordered(
        result.event_summary,
        EVENT_SUMMARY_COLUMNS,
        ["event_source", "event_type", "horizon"],
    ).to_csv(paths["event_summary"], index=False)
    paths["markdown"].write_text(
        render_event_study_markdown(result, metadata),
        encoding="utf-8",
    )
    return paths


def _skip_summary(samples: pd.DataFrame) -> pd.DataFrame:
    if samples.empty or "included" not in samples.columns:
        return pd.DataFrame(columns=["skip_reason", "sample_count"])
    skipped = samples[~samples["included"].astype(bool)]
    if skipped.empty:
        return pd.DataFrame([{"skip_reason": "(none)", "sample_count": 0}])
    return (
        skipped.groupby("skip_reason", dropna=False)
        .size()
        .reset_index(name="sample_count")
        .sort_values("skip_reason", kind="mergesort")
        .reset_index(drop=True)
    )


def _small_sample_note(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "没有生成可统计窗口，样本过少风险为 high。"
    min_count = int(summary["sample_count"].min())
    if min_count < 5:
        return f"存在样本过少风险，最小 horizon 样本数为 {min_count}。"
    return "未发现小于 5 的 horizon 样本桶；仍需结合事件类型和年份分布复核。"


def _ordered(frame: pd.DataFrame, columns: list[str], sort_columns: list[str]) -> pd.DataFrame:
    result = frame.copy() if not frame.empty else pd.DataFrame(columns=columns)
    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, columns]
    sort_keys = [column for column in sort_columns if column in result.columns]
    if sort_keys and not result.empty:
        result = result.sort_values(sort_keys, kind="mergesort", na_position="last")
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
