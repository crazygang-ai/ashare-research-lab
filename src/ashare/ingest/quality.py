"""Data quality reporting for the Phase 1a-7 real data ingest pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from collections.abc import Mapping, Sequence

import pandas as pd

from ashare.ingest.contracts import (
    DATASET_COLUMNS,
    FieldValidationIssue,
    duplicate_key_count,
)


@dataclass(frozen=True)
class DataQualityReport:
    """Structured quality report emitted after a real pilot ingest."""

    source: str
    effective_source: str
    source_tag: str
    universe: str
    index_code: str
    start_date: date
    end_date: date
    universe_as_of_date: date
    dataset_summary: pd.DataFrame
    field_summary: pd.DataFrame
    issues: pd.DataFrame
    cache_summary: pd.DataFrame
    warnings: tuple[str, ...]


def build_data_quality_report(
    *,
    source: str,
    effective_source: str,
    source_tag: str,
    universe: str,
    index_code: str,
    start_date: date,
    end_date: date,
    universe_as_of_date: date,
    frames: Mapping[str, pd.DataFrame],
    issues: Sequence[FieldValidationIssue],
    cache_events: Sequence[Mapping[str, object]],
    warnings: Sequence[str],
    sample_stock_codes: Sequence[str],
    universe_members_mode: str,
) -> DataQualityReport:
    """Build quality summary tables and report-level warnings."""
    report_warnings = list(warnings)
    if effective_source == "csv_fallback":
        report_warnings.append("CSV fallback was used after primary provider failure.")
    if universe_members_mode != "historical":
        report_warnings.append("Index members are treated as a current snapshot, not full PIT history.")

    dataset_summary = _dataset_summary(frames, sample_stock_codes)
    field_summary = _field_summary(frames)
    issue_frame = _issues_frame(issues)
    cache_summary = pd.DataFrame(cache_events)
    if cache_summary.empty:
        cache_summary = pd.DataFrame(
            columns=["dataset", "cache_mode", "status", "source", "params_hash", "path"]
        )

    if sample_stock_codes:
        sample_note = "sample_stock_codes: " + ", ".join(sample_stock_codes)
        report_warnings.append(sample_note)

    return DataQualityReport(
        source=source,
        effective_source=effective_source,
        source_tag=source_tag,
        universe=universe,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        universe_as_of_date=universe_as_of_date,
        dataset_summary=dataset_summary,
        field_summary=field_summary,
        issues=issue_frame,
        cache_summary=cache_summary,
        warnings=tuple(dict.fromkeys(report_warnings)),
    )


def write_data_quality_report(
    report: DataQualityReport,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write Markdown plus CSV report files."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown": output / "data_quality_report.md",
        "dataset_summary": output / "dataset_summary.csv",
        "field_summary": output / "field_summary.csv",
        "issues": output / "issues.csv",
        "cache_summary": output / "cache_summary.csv",
    }
    if not overwrite:
        existing = [path for path in paths.values() if path.exists()]
        if existing:
            joined = ", ".join(str(path) for path in existing)
            raise FileExistsError(f"Quality report file(s) already exist: {joined}")

    report.dataset_summary.to_csv(paths["dataset_summary"], index=False)
    report.field_summary.to_csv(paths["field_summary"], index=False)
    report.issues.to_csv(paths["issues"], index=False)
    report.cache_summary.to_csv(paths["cache_summary"], index=False)
    paths["markdown"].write_text(_markdown(report), encoding="utf-8")
    return paths


def _dataset_summary(
    frames: Mapping[str, pd.DataFrame],
    sample_stock_codes: Sequence[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    trading_dates = _date_count(frames.get("trading_calendar"), "trade_date")
    sample_size = len(sample_stock_codes)
    for dataset, columns in DATASET_COLUMNS.items():
        frame = frames.get(dataset, pd.DataFrame(columns=columns))
        date_column = _primary_date_column(dataset)
        start = frame[date_column].min() if date_column in frame and not frame.empty else None
        end = frame[date_column].max() if date_column in frame and not frame.empty else None
        stock_count = int(frame["stock_code"].nunique()) if "stock_code" in frame else None
        coverage_rate = None
        if dataset in {"daily_prices", "valuation_daily"} and sample_size and trading_dates:
            coverage_rate = len(frame) / (sample_size * trading_dates)
        rows.append(
            {
                "dataset": dataset,
                "row_count": int(len(frame)),
                "stock_count": stock_count,
                "start_date": start,
                "end_date": end,
                "duplicate_key_rows": duplicate_key_count(dataset, frame),
                "coverage_rate": coverage_rate,
            }
        )
    return pd.DataFrame(rows)


def _field_summary(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dataset, columns in DATASET_COLUMNS.items():
        frame = frames.get(dataset, pd.DataFrame(columns=columns))
        row_count = len(frame)
        for column in columns:
            if column in frame.columns:
                missing_count = int(frame[column].isna().sum())
            else:
                missing_count = row_count
            rows.append(
                {
                    "dataset": dataset,
                    "field": column,
                    "row_count": row_count,
                    "missing_count": missing_count,
                    "missing_rate": missing_count / row_count if row_count else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _issues_frame(issues: Sequence[FieldValidationIssue]) -> pd.DataFrame:
    rows = [
        {
            "dataset": issue.dataset,
            "severity": issue.severity,
            "code": issue.code,
            "message": issue.message,
            "row_count": issue.row_count,
        }
        for issue in issues
    ]
    if not rows:
        rows.append(
            {
                "dataset": "all",
                "severity": "info",
                "code": "no_validation_issues",
                "message": "No validation issues were emitted.",
                "row_count": None,
            }
        )
    return pd.DataFrame(rows)


def _markdown(report: DataQualityReport) -> str:
    warning_text = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    sample_codes = _sample_codes_from_warnings(report.warnings)
    return "\n".join(
        [
            "# Phase 1a-7 Data Quality Report",
            "",
            f"- source: {report.source}",
            f"- effective_source: {report.effective_source}",
            f"- source_tag: {report.source_tag}",
            f"- universe: {report.universe}",
            f"- index_code: {report.index_code}",
            f"- date_range: {report.start_date.isoformat()} to {report.end_date.isoformat()}",
            f"- universe_as_of_date: {report.universe_as_of_date.isoformat()}",
            f"- sample_stock_codes: {sample_codes}",
            f"- csv_fallback_used: {report.effective_source == 'csv_fallback'}",
            "",
            "## Dataset Summary",
            "",
            _frame_text(report.dataset_summary),
            "",
            "## Field Missing Rates",
            "",
            _frame_text(report.field_summary),
            "",
            "## Duplicate Key Check",
            "",
            "See `dataset_summary.csv` column `duplicate_key_rows`.",
            "",
            "## Price And Valuation Checks",
            "",
            "See `issues.csv` for price consistency and valuation warnings.",
            "",
            "## Cache Summary",
            "",
            _frame_text(report.cache_summary),
            "",
            "## PIT Limitations And Warnings",
            "",
            warning_text,
            "",
        ]
    )


def _primary_date_column(dataset: str) -> str:
    if dataset == "securities":
        return "list_date"
    if dataset == "universe_members":
        return "in_date"
    return "trade_date"


def _frame_text(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(empty)"
    return frame.to_string(index=False)


def _date_count(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame:
        return 0
    return int(frame[column].nunique())


def _sample_codes_from_warnings(warnings: Sequence[str]) -> str:
    for warning in warnings:
        if warning.startswith("sample_stock_codes: "):
            return warning.removeprefix("sample_stock_codes: ")
    return "(not limited)"
