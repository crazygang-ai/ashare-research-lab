"""Phase 7 formal daily research report assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date
from ashare.reports.data_quality_gate import DataQualityGateResult
from ashare.reports.run_summary import (
    ArtifactBundle,
    artifact_run_value,
    fail_if_exists,
    markdown_table,
    ordered_frame,
    read_artifact_csv,
    read_artifact_json,
    stringify,
    write_json,
)


DAILY_REPORT_FILES = {
    "markdown": "daily_report.md",
    "daily_candidates": "daily_candidates.csv",
    "daily_score_summary": "daily_score_summary.csv",
    "daily_factor_contributions": "daily_factor_contributions.csv",
    "daily_risk_summary": "daily_risk_summary.csv",
    "daily_changes": "daily_changes.csv",
    "daily_validation_gate_summary": "daily_validation_gate_summary.csv",
    "daily_watchlist_summary": "daily_watchlist_summary.csv",
    "daily_factor_validation_summary": "daily_factor_validation_summary.csv",
    "daily_backtest_summary": "daily_backtest_summary.csv",
    "daily_event_study_summary": "daily_event_study_summary.csv",
    "daily_input_artifacts": "daily_input_artifacts.json",
    "daily_metadata": "daily_metadata.json",
}

DAILY_CHANGE_COLUMNS = [
    "change_type",
    "stock_code",
    "current_rank",
    "compare_rank",
    "rank_delta",
    "current_source",
    "compare_source",
    "message",
]

DAILY_RISK_COLUMNS = [
    "source_type",
    "stock_code",
    "evidence_date",
    "evidence_type",
    "severity",
    "summary",
    "evidence_id",
    "source_run_id",
]


@dataclass(frozen=True)
class DailyReportResult:
    markdown: str
    daily_candidates: pd.DataFrame
    daily_score_summary: pd.DataFrame
    daily_factor_contributions: pd.DataFrame
    daily_risk_summary: pd.DataFrame
    daily_changes: pd.DataFrame
    daily_validation_gate_summary: pd.DataFrame
    daily_watchlist_summary: pd.DataFrame
    daily_factor_validation_summary: pd.DataFrame
    daily_backtest_summary: pd.DataFrame
    daily_event_study_summary: pd.DataFrame
    input_artifacts: list[dict[str, Any]]
    metadata: dict[str, Any]


def build_daily_report(
    connection: duckdb.DuckDBPyConnection,
    *,
    as_of_date: DateLike,
    source_run_id: str,
    scan_bundle: ArtifactBundle,
    score_bundle: ArtifactBundle,
    backtest_bundle: ArtifactBundle,
    event_study_bundle: ArtifactBundle,
    data_quality_gate: DataQualityGateResult,
    repo_root: Path,
    metadata: Mapping[str, Any],
    compare_scan_bundle: ArtifactBundle | None = None,
    compare_score_bundle: ArtifactBundle | None = None,
    factor_validation_bundle: ArtifactBundle | None = None,
    watchlist_codes: Sequence[str] = (),
    recent_days: int = 30,
) -> DailyReportResult:
    """Build report frames and Markdown from already generated artifacts."""
    parsed_as_of = parse_as_of_date(as_of_date)
    score_metadata = read_artifact_json(score_bundle, "score_metadata.json")
    data_source = _first_non_empty(
        metadata.get("data_source"),
        score_metadata.get("data_source"),
    )
    index_code = _first_non_empty(
        metadata.get("index_code"),
        score_metadata.get("index_code"),
    )
    top_n = _int_value(_first_non_empty(metadata.get("top_n"), score_metadata.get("top_n")), 20)
    watchlist_code_list = _dedupe_codes(watchlist_codes)

    candidates = _daily_candidates(scan_bundle, score_bundle, top_n=top_n)
    score_summary = _score_summary(score_bundle, top_n=top_n)
    factor_contributions = _factor_contributions(score_bundle, score_summary)
    changes = _candidate_changes(
        current=candidates,
        current_score=score_summary,
        compare_scan_bundle=compare_scan_bundle,
        compare_score_bundle=compare_score_bundle,
        top_n=top_n,
    )
    validation_gate_summary = _validation_gate_summary(score_bundle)
    risk_summary = _risk_summary(
        connection,
        parsed_as_of=parsed_as_of,
        source_run_id=source_run_id,
        stock_codes=_report_stock_codes(candidates, score_summary),
        score_bundle=score_bundle,
        recent_days=recent_days,
        data_source=str(data_source) if data_source is not None else None,
    )
    watchlist_summary = _watchlist_summary(
        watchlist_codes=watchlist_code_list,
        candidates=candidates,
        score_summary=score_summary,
        risk_summary=risk_summary,
    )
    validation_summary = _factor_validation_summary(
        factor_validation_bundle=factor_validation_bundle,
        score_bundle=score_bundle,
        score_metadata=score_metadata,
        repo_root=repo_root,
    )
    backtest_summary = _backtest_summary(backtest_bundle)
    event_summary = _event_study_summary(event_study_bundle)
    input_artifacts = [
        bundle.to_metadata()
        for bundle in [
            scan_bundle,
            score_bundle,
            backtest_bundle,
            event_study_bundle,
            *( [factor_validation_bundle] if factor_validation_bundle is not None else [] ),
            *( [compare_scan_bundle] if compare_scan_bundle is not None else [] ),
            *( [compare_score_bundle] if compare_score_bundle is not None else [] ),
        ]
    ]

    report_metadata: dict[str, Any] = {
        "title": "Daily Research Report",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "as_of_date": parsed_as_of.isoformat(),
        "source_run_id": source_run_id,
        "index_code": index_code,
        "top_n": top_n,
        "recent_days": recent_days,
        "watchlist_codes": watchlist_code_list,
        "watchlist_count": len(watchlist_code_list),
        "input_artifacts": input_artifacts,
        "data_quality_gate_summary": data_quality_gate.summary,
        "data_quality_has_blocking_failures": data_quality_gate.has_blocking_failures,
        **dict(metadata),
    }
    markdown = render_daily_markdown(
        candidates=candidates,
        score_summary=score_summary,
        factor_contributions=factor_contributions,
        risk_summary=risk_summary,
        changes=changes,
        validation_gate_summary=validation_gate_summary,
        watchlist_summary=watchlist_summary,
        validation_summary=validation_summary,
        backtest_summary=backtest_summary,
        event_summary=event_summary,
        gate=data_quality_gate.table,
        metadata=report_metadata,
    )
    return DailyReportResult(
        markdown=markdown,
        daily_candidates=candidates,
        daily_score_summary=score_summary,
        daily_factor_contributions=factor_contributions,
        daily_risk_summary=risk_summary,
        daily_changes=changes,
        daily_validation_gate_summary=validation_gate_summary,
        daily_watchlist_summary=watchlist_summary,
        daily_factor_validation_summary=validation_summary,
        daily_backtest_summary=backtest_summary,
        daily_event_study_summary=event_summary,
        input_artifacts=input_artifacts,
        metadata=report_metadata,
    )


def render_daily_markdown(
    *,
    candidates: pd.DataFrame,
    score_summary: pd.DataFrame,
    factor_contributions: pd.DataFrame,
    risk_summary: pd.DataFrame,
    changes: pd.DataFrame,
    validation_gate_summary: pd.DataFrame,
    watchlist_summary: pd.DataFrame,
    validation_summary: pd.DataFrame,
    backtest_summary: pd.DataFrame,
    event_summary: pd.DataFrame,
    gate: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> str:
    """Render the daily report Markdown."""
    input_rows = pd.DataFrame(
        [
            {
                "kind": item.get("kind"),
                "run_id": item.get("run_id"),
                "input_source_run_id": artifact_run_value(item, "source_run_id"),
                "input_as_of_date": artifact_run_value(item, "as_of_date"),
                "input_config_hash": artifact_run_value(item, "config_hash"),
                "input_data_snapshot_id": artifact_run_value(item, "data_snapshot_id"),
                "requested_run_id": item.get("requested_run_id"),
                "resolved_via": item.get("resolved_via"),
                "artifact_ids": _artifact_ids(item),
                "file_count": len(item.get("files", {})) if isinstance(item.get("files"), dict) else 0,
                "warnings": "; ".join(item.get("warnings", [])),
            }
            for item in metadata.get("input_artifacts", [])
            if isinstance(item, Mapping)
        ]
    )
    lines = [
        "# Daily Research Report",
        "",
        "## Metadata",
        "",
        f"- as_of_date: {stringify(metadata.get('as_of_date'))}",
        f"- run_id: {stringify(metadata.get('run_id'))}",
        f"- run_mode: {stringify(metadata.get('run_mode'))}",
        f"- db_path: {stringify(metadata.get('db_path'))}",
        f"- source_run_id: {stringify(metadata.get('source_run_id'))}",
        f"- index_code: {stringify(metadata.get('index_code'))}",
        f"- config_hash: {stringify(metadata.get('config_hash'))}",
        f"- data_snapshot_id: {stringify(metadata.get('data_snapshot_id'))}",
        f"- git_sha: {stringify(metadata.get('git_sha'))}",
        f"- worktree_clean: {stringify(metadata.get('worktree_clean'))}",
        "",
        "## Input Artifact Ids And Run Ids",
        "",
        markdown_table(input_rows),
        "",
        "## Data Quality Gate Summary",
        "",
        _gate_summary(gate),
        "",
        markdown_table(gate),
        "",
        "## Validation Gate Summary",
        "",
        _validation_gate_note(validation_gate_summary),
        "",
        markdown_table(validation_gate_summary),
        "",
        "## Today Candidate Top N",
        "",
        markdown_table(candidates, max_rows=_top_n(metadata)),
        "",
        "## Added, Removed, And Rank Changes",
        "",
        _changes_note(changes, metadata=metadata),
        "",
        markdown_table(changes),
        "",
        "## Watchlist Summary",
        "",
        _watchlist_note(watchlist_summary, metadata=metadata),
        "",
        markdown_table(watchlist_summary),
        "",
        "## Composite Score Top N",
        "",
        markdown_table(score_summary, max_rows=_top_n(metadata)),
        "",
        "## Factor Contribution Breakdown",
        "",
        markdown_table(factor_contributions, max_rows=50),
        "",
        "## Hard Filter Exclusion Summary",
        "",
        markdown_table(_risk_filter_rows(risk_summary), max_rows=50),
        "",
        "## Main Risk Tips",
        "",
        markdown_table(risk_summary, max_rows=50),
        "",
        "## Recent Announcement And Event Evidence",
        "",
        markdown_table(_risk_evidence_rows(risk_summary), max_rows=50),
        "",
        "## Event Study Summary",
        "",
        markdown_table(event_summary, max_rows=30),
        "",
        "## Single Factor Validation Summary",
        "",
        markdown_table(validation_summary, max_rows=50),
        "",
        "## Backtest Performance Summary",
        "",
        markdown_table(backtest_summary, max_rows=50),
        "",
        "## Data Limits And Known Risks",
        "",
        "- 本报告只汇总显式传入的已有产物，不在日报内重算因子、评分、回测或事件研究。",
        "- PIT 可见性仍为 date 级，不区分盘前、盘中和盘后披露。",
        "- 单因子验证收益是统计标签，不是可执行交易收益。",
        "- 回测摘要依赖既有回测假设和成本模型，不代表未来表现。",
        "- LLM 公告解析如存在，仅作为证据展示，不直接接入总分。",
        "",
        "## Research Use Only",
        "",
        "- 本报告是研究辅助输出，不是交易指令。",
        "- It does not contain buy, sell, target price, or position-size instructions.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_daily_report(
    result: DailyReportResult,
    output_dir: str | Path,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write Markdown, CSV, and JSON daily report artifacts."""
    resolved = Path(output_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    paths = {key: resolved / filename for key, filename in DAILY_REPORT_FILES.items()}
    fail_if_exists(list(paths.values()), overwrite=overwrite)

    result.daily_candidates.to_csv(paths["daily_candidates"], index=False)
    result.daily_score_summary.to_csv(paths["daily_score_summary"], index=False)
    result.daily_factor_contributions.to_csv(paths["daily_factor_contributions"], index=False)
    result.daily_risk_summary.to_csv(paths["daily_risk_summary"], index=False)
    result.daily_changes.to_csv(paths["daily_changes"], index=False)
    result.daily_validation_gate_summary.to_csv(
        paths["daily_validation_gate_summary"],
        index=False,
    )
    result.daily_watchlist_summary.to_csv(paths["daily_watchlist_summary"], index=False)
    result.daily_factor_validation_summary.to_csv(
        paths["daily_factor_validation_summary"],
        index=False,
    )
    result.daily_backtest_summary.to_csv(paths["daily_backtest_summary"], index=False)
    result.daily_event_study_summary.to_csv(paths["daily_event_study_summary"], index=False)
    write_json(paths["daily_input_artifacts"], result.input_artifacts)
    write_json(paths["daily_metadata"], result.metadata)
    paths["markdown"].write_text(result.markdown, encoding="utf-8")
    return paths


def _daily_candidates(
    scan_bundle: ArtifactBundle,
    score_bundle: ArtifactBundle,
    *,
    top_n: int,
) -> pd.DataFrame:
    candidates = read_artifact_csv(scan_bundle, "candidates.csv")
    score = read_artifact_csv(score_bundle, "scored_candidates.csv")
    if candidates.empty:
        base = pd.DataFrame(
            columns=[
                "rank",
                "stock_code",
                "stock_name",
                "industry_l1",
                "industry_l2",
                "selection_reason",
                "risk_tips",
            ]
        )
    else:
        base_columns = [
            column
            for column in [
                "rank",
                "stock_code",
                "stock_name",
                "industry_l1",
                "industry_l2",
                "selection_reason",
                "risk_tips",
            ]
            if column in candidates.columns
        ]
        base = candidates.loc[:, base_columns].copy()
    if not score.empty and "stock_code" in base.columns:
        score_cols = [
            column
            for column in ["stock_code", "rank", "total_score", "risk_penalty", "hard_filter_passed"]
            if column in score.columns
        ]
        score_part = score.loc[:, score_cols].rename(columns={"rank": "score_rank"})
        base = base.merge(score_part, on="stock_code", how="left")
    if "rank" in base.columns and not base.empty:
        base = base.sort_values("rank", kind="mergesort")
    return base.head(top_n).reset_index(drop=True)


def _score_summary(score_bundle: ArtifactBundle, *, top_n: int) -> pd.DataFrame:
    score = read_artifact_csv(score_bundle, "scored_candidates.csv")
    columns = [
        "rank",
        "stock_code",
        "stock_name",
        "industry_l1",
        "industry_l2",
        "total_score",
        "financial_score",
        "valuation_score",
        "momentum_score",
        "event_score",
        "risk_penalty",
        "hard_filter_passed",
        "selection_reason",
        "risk_tips",
    ]
    return ordered_frame(score, columns, ["rank"]).head(top_n).reset_index(drop=True)


def _factor_contributions(score_bundle: ArtifactBundle, score_summary: pd.DataFrame) -> pd.DataFrame:
    factors = read_artifact_csv(score_bundle, "factor_normalized_scores.csv")
    columns = [
        "stock_code",
        "factor_name",
        "score_role",
        "score_group",
        "raw_factor_value",
        "normalized_score",
        "factor_weight",
        "weighted_contribution",
        "validation_status",
    ]
    if not score_summary.empty and "stock_code" in factors.columns:
        codes = set(score_summary["stock_code"].astype(str))
        factors = factors[factors["stock_code"].astype(str).isin(codes)].copy()
    return ordered_frame(
        factors,
        columns,
        ["stock_code", "score_group", "factor_name"],
    )


def _validation_gate_summary(score_bundle: ArtifactBundle) -> pd.DataFrame:
    gate = read_artifact_csv(score_bundle, "validation_gate.csv")
    columns = ["validation_status", "factor_count", "factors", "reasons"]
    if gate.empty:
        return pd.DataFrame(columns=columns)
    status_column = "validation_status" if "validation_status" in gate.columns else "status"
    if status_column not in gate.columns:
        gate = gate.copy()
        gate["validation_status"] = "UNKNOWN"
        status_column = "validation_status"
    rows: list[dict[str, object]] = []
    for status, group in gate.groupby(status_column, dropna=False, sort=True):
        factors = (
            group["factor_name"].astype(str).tolist()
            if "factor_name" in group.columns
            else []
        )
        reasons = (
            group["reason"].dropna().astype(str).tolist()
            if "reason" in group.columns
            else []
        )
        rows.append(
            {
                "validation_status": stringify(status) or "UNKNOWN",
                "factor_count": len(group),
                "factors": "; ".join(item for item in factors if item),
                "reasons": "; ".join(dict.fromkeys(item for item in reasons if item)),
            }
        )
    return ordered_frame(pd.DataFrame(rows), columns, ["validation_status"])


def _watchlist_summary(
    *,
    watchlist_codes: Sequence[str],
    candidates: pd.DataFrame,
    score_summary: pd.DataFrame,
    risk_summary: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "stock_code",
        "in_candidate_top_n",
        "candidate_rank",
        "candidate_reason",
        "in_score_top_n",
        "score_rank",
        "total_score",
        "hard_filter_passed",
        "risk_tip_count",
        "latest_evidence_date",
        "evidence_types",
    ]
    codes = _dedupe_codes(watchlist_codes)
    if not codes:
        return pd.DataFrame(columns=columns)
    candidate_lookup = _row_lookup(candidates)
    score_lookup = _row_lookup(score_summary)
    risk_lookup = _risk_lookup(risk_summary)
    rows: list[dict[str, object]] = []
    for code in codes:
        candidate = candidate_lookup.get(code, {})
        score = score_lookup.get(code, {})
        risks = risk_lookup.get(code, pd.DataFrame(columns=DAILY_RISK_COLUMNS))
        evidence_types = (
            "; ".join(
                dict.fromkeys(
                    stringify(value)
                    for value in risks.get("evidence_type", pd.Series(dtype=object)).tolist()
                    if stringify(value)
                )
            )
            if not risks.empty
            else ""
        )
        latest_evidence_date = (
            max(
                [
                    stringify(value)
                    for value in risks.get("evidence_date", pd.Series(dtype=object)).tolist()
                    if stringify(value)
                ],
                default="",
            )
            if not risks.empty
            else ""
        )
        rows.append(
            {
                "stock_code": code,
                "in_candidate_top_n": bool(candidate),
                "candidate_rank": candidate.get("rank"),
                "candidate_reason": candidate.get("selection_reason"),
                "in_score_top_n": bool(score),
                "score_rank": score.get("rank"),
                "total_score": score.get("total_score"),
                "hard_filter_passed": score.get("hard_filter_passed"),
                "risk_tip_count": len(risks),
                "latest_evidence_date": latest_evidence_date,
                "evidence_types": evidence_types,
            }
        )
    return ordered_frame(pd.DataFrame(rows), columns)


def _candidate_changes(
    *,
    current: pd.DataFrame,
    current_score: pd.DataFrame,
    compare_scan_bundle: ArtifactBundle | None,
    compare_score_bundle: ArtifactBundle | None,
    top_n: int,
) -> pd.DataFrame:
    current_rank = _rank_map(current, source="scan")
    current_source = "scan"
    if not current_rank:
        current_rank = _rank_map(current_score, source="score")
        current_source = "score"

    compare_frame = pd.DataFrame()
    compare_source = ""
    if compare_scan_bundle is not None and compare_scan_bundle.run_id is not None:
        compare_frame = read_artifact_csv(compare_scan_bundle, "candidates.csv")
        compare_source = "compare_scan"
    if compare_frame.empty and compare_score_bundle is not None and compare_score_bundle.run_id is not None:
        compare_frame = read_artifact_csv(compare_score_bundle, "scored_candidates.csv")
        compare_source = "compare_score"

    if not current_rank and compare_frame.empty:
        return pd.DataFrame(columns=DAILY_CHANGE_COLUMNS)
    if compare_frame.empty:
        return pd.DataFrame(columns=DAILY_CHANGE_COLUMNS)

    compare_rank = _rank_map(compare_frame, source=compare_source)
    rows: list[dict[str, object]] = []
    current_codes = set(current_rank)
    compare_codes = set(compare_rank)
    for stock_code in sorted(current_codes - compare_codes):
        rows.append(
            _change_row(
                "added",
                stock_code,
                current_rank.get(stock_code),
                None,
                current_source,
                compare_source,
            )
        )
    for stock_code in sorted(compare_codes - current_codes):
        rows.append(
            _change_row(
                "removed",
                stock_code,
                None,
                compare_rank.get(stock_code),
                current_source,
                compare_source,
            )
        )
    for stock_code in sorted(current_codes & compare_codes):
        current_value = current_rank[stock_code]
        compare_value = compare_rank[stock_code]
        if current_value != compare_value:
            rows.append(
                _change_row(
                    "rank_changed",
                    stock_code,
                    current_value,
                    compare_value,
                    current_source,
                    compare_source,
                )
            )
    changes = pd.DataFrame(rows, columns=DAILY_CHANGE_COLUMNS)
    if not changes.empty:
        changes = changes.sort_values(
            ["change_type", "current_rank", "stock_code"],
            kind="mergesort",
            na_position="last",
        )
    return changes.head(max(top_n * 3, top_n)).reset_index(drop=True)


def _change_row(
    change_type: str,
    stock_code: str,
    current_rank: int | None,
    compare_rank: int | None,
    current_source: str,
    compare_source: str,
) -> dict[str, object]:
    rank_delta = (
        None
        if current_rank is None or compare_rank is None
        else int(compare_rank) - int(current_rank)
    )
    return {
        "change_type": change_type,
        "stock_code": stock_code,
        "current_rank": current_rank,
        "compare_rank": compare_rank,
        "rank_delta": rank_delta,
        "current_source": current_source,
        "compare_source": compare_source,
        "message": _change_message(change_type, rank_delta),
    }


def _risk_summary(
    connection: duckdb.DuckDBPyConnection,
    *,
    parsed_as_of: date,
    source_run_id: str,
    stock_codes: Sequence[str],
    score_bundle: ArtifactBundle,
    recent_days: int,
    data_source: str | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    hard_exclusions = read_artifact_csv(score_bundle, "hard_filter_exclusions.csv")
    for row in hard_exclusions.itertuples(index=False):
        rows.append(
            {
                "source_type": "hard_filter",
                "stock_code": getattr(row, "stock_code", ""),
                "evidence_date": stringify(getattr(row, "as_of_date", parsed_as_of)),
                "evidence_type": getattr(row, "hard_filter_name", ""),
                "severity": "blocking",
                "summary": getattr(row, "exclusion_reason", ""),
                "evidence_id": "",
                "source_run_id": source_run_id,
            }
        )
    score = read_artifact_csv(score_bundle, "scored_candidates.csv")
    if not score.empty and "risk_tips" in score.columns:
        for row in score.itertuples(index=False):
            tips = stringify(getattr(row, "risk_tips", ""))
            if tips and tips != "未触发本阶段软风险扣分":
                rows.append(
                    {
                        "source_type": "score_risk",
                        "stock_code": getattr(row, "stock_code", ""),
                        "evidence_date": parsed_as_of.isoformat(),
                        "evidence_type": "risk_tips",
                        "severity": "warning",
                        "summary": tips,
                        "evidence_id": "",
                        "source_run_id": source_run_id,
                    }
                )
    rows.extend(
        _recent_announcements(
            connection,
            parsed_as_of=parsed_as_of,
            stock_codes=stock_codes,
            recent_days=recent_days,
            source_tag=None if data_source == "legacy" else data_source,
        )
    )
    rows.extend(
        _recent_risk_events(
            connection,
            parsed_as_of=parsed_as_of,
            stock_codes=stock_codes,
            recent_days=recent_days,
            source=None if data_source == "legacy" else data_source,
        )
    )
    frame = pd.DataFrame(rows, columns=DAILY_RISK_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["source_type", "stock_code", "evidence_date", "evidence_id"],
            kind="mergesort",
            na_position="last",
        )
    return frame.reset_index(drop=True)


def _recent_announcements(
    connection: duckdb.DuckDBPyConnection,
    *,
    parsed_as_of: date,
    stock_codes: Sequence[str],
    recent_days: int,
    source_tag: str | None,
) -> list[dict[str, object]]:
    if not stock_codes or not _table_exists(connection, "announcements"):
        return []
    placeholders = ", ".join("?" for _ in stock_codes)
    start = parsed_as_of - timedelta(days=recent_days)
    sql = f"""
        SELECT announcement_id, stock_code, title, announcement_type, publish_time, effective_date
        FROM announcements
        WHERE CAST(publish_time AS DATE) <= ?
          AND effective_date BETWEEN ? AND ?
          AND stock_code IN ({placeholders})
    """
    params: list[object] = [parsed_as_of, start, parsed_as_of, *stock_codes]
    if source_tag is not None:
        sql += " AND COALESCE(source_tag, source) = ?"
        params.append(source_tag)
    sql += " ORDER BY effective_date DESC, stock_code, announcement_id"
    frame = connection.execute(
        sql,
        params,
    ).df()
    if frame.empty:
        return []
    llm_summary = _announcement_summary_lookup(
        connection,
        frame["announcement_id"].astype(str),
        source_tag=source_tag,
    )
    rows: list[dict[str, object]] = []
    for item in frame.itertuples(index=False):
        announcement_id = str(item.announcement_id)
        rows.append(
            {
                "source_type": "announcement",
                "stock_code": item.stock_code,
                "evidence_date": stringify(item.effective_date),
                "evidence_type": item.announcement_type,
                "severity": "info",
                "summary": llm_summary.get(announcement_id) or stringify(item.title),
                "evidence_id": announcement_id,
                "source_run_id": "",
            }
        )
    return rows


def _recent_risk_events(
    connection: duckdb.DuckDBPyConnection,
    *,
    parsed_as_of: date,
    stock_codes: Sequence[str],
    recent_days: int,
    source: str | None,
) -> list[dict[str, object]]:
    if not stock_codes or not _table_exists(connection, "risk_events"):
        return []
    placeholders = ", ".join("?" for _ in stock_codes)
    start = parsed_as_of - timedelta(days=recent_days)
    sql = f"""
        SELECT event_id, stock_code, event_type, event_date, effective_date
        FROM risk_events
        WHERE CAST(publish_time AS DATE) <= ?
          AND effective_date BETWEEN ? AND ?
          AND stock_code IN ({placeholders})
    """
    params: list[object] = [parsed_as_of, start, parsed_as_of, *stock_codes]
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY effective_date DESC, stock_code, event_id"
    frame = connection.execute(
        sql,
        params,
    ).df()
    rows: list[dict[str, object]] = []
    for item in frame.itertuples(index=False):
        rows.append(
            {
                "source_type": "risk_event",
                "stock_code": item.stock_code,
                "evidence_date": stringify(item.effective_date or item.event_date),
                "evidence_type": item.event_type,
                "severity": "warning",
                "summary": f"Risk event: {item.event_type}",
                "evidence_id": item.event_id,
                "source_run_id": "",
            }
        )
    return rows


def _announcement_summary_lookup(
    connection: duckdb.DuckDBPyConnection,
    announcement_ids: Sequence[str],
    source_tag: str | None = None,
) -> dict[str, str]:
    ids = tuple(dict.fromkeys(str(item) for item in announcement_ids if str(item)))
    if not ids or not _table_exists(connection, "announcement_llm_results"):
        return {}
    placeholders = ", ".join("?" for _ in ids)
    frame = connection.execute(
        f"""
        SELECT announcement_id, summary
        FROM announcement_llm_results
        WHERE announcement_id IN ({placeholders})
          AND status = 'success'
          {"AND COALESCE(source_tag, source) = ?" if source_tag is not None else ""}
        ORDER BY created_at DESC
        """,
        [*ids, *([source_tag] if source_tag is not None else [])],
    ).df()
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        result.setdefault(str(row.announcement_id), stringify(row.summary))
    return result


def _factor_validation_summary(
    *,
    factor_validation_bundle: ArtifactBundle | None,
    score_bundle: ArtifactBundle,
    score_metadata: Mapping[str, Any],
    repo_root: Path,
) -> pd.DataFrame:
    if factor_validation_bundle is not None and factor_validation_bundle.run_id is not None:
        frame = read_artifact_csv(factor_validation_bundle, "ic_summary.csv")
        return ordered_frame(
            frame,
            [
                "factor_name",
                "horizon",
                "valid_oriented_ic_dates",
                "mean_oriented_rank_ic",
                "oriented_icir",
            ],
            ["factor_name", "horizon"],
        )
    validation_dir = score_metadata.get("validation_dir")
    if isinstance(validation_dir, str) and validation_dir:
        path = Path(validation_dir)
        resolved = path if path.is_absolute() else repo_root / path
        ic_path = resolved / "ic_summary.csv"
        if ic_path.exists():
            frame = pd.read_csv(ic_path)
            return ordered_frame(
                frame,
                [
                    "factor_name",
                    "horizon",
                    "valid_oriented_ic_dates",
                    "mean_oriented_rank_ic",
                    "oriented_icir",
                ],
                ["factor_name", "horizon"],
            )
    gate = read_artifact_csv(score_bundle, "validation_gate.csv")
    return ordered_frame(
        gate,
        ["factor_name", "validation_status", "reason"],
        ["factor_name"],
    )


def _backtest_summary(backtest_bundle: ArtifactBundle) -> pd.DataFrame:
    metrics = read_artifact_csv(backtest_bundle, "metrics.csv")
    if metrics.empty:
        return pd.DataFrame(columns=["metric", "value"])
    row = metrics.iloc[0].to_dict()
    keys = [
        "total_return",
        "annualized_return",
        "volatility",
        "max_drawdown",
        "sharpe",
        "benchmark_cap_weight_return",
        "benchmark_equal_weight_return",
        "excess_return_vs_cap_weight",
        "excess_return_vs_equal_weight",
        "total_cost",
    ]
    return pd.DataFrame(
        [{"metric": key, "value": row.get(key)} for key in keys if key in row]
    )


def _event_study_summary(event_study_bundle: ArtifactBundle) -> pd.DataFrame:
    summary = read_artifact_csv(event_study_bundle, "event_summary.csv")
    return ordered_frame(
        summary,
        [
            "event_source",
            "event_type",
            "horizon",
            "sample_count",
            "mean_event_return",
            "median_event_return",
            "mean_excess_return",
            "win_rate",
            "excess_win_rate",
        ],
        ["event_source", "event_type", "horizon"],
    )


def _report_stock_codes(candidates: pd.DataFrame, score_summary: pd.DataFrame) -> tuple[str, ...]:
    codes: list[str] = []
    for frame in [candidates, score_summary]:
        if not frame.empty and "stock_code" in frame.columns:
            codes.extend(str(value) for value in frame["stock_code"].dropna().tolist())
    return tuple(dict.fromkeys(codes))


def _rank_map(frame: pd.DataFrame, *, source: str) -> dict[str, int]:
    _ = source
    if frame.empty or "stock_code" not in frame.columns:
        return {}
    result: dict[str, int] = {}
    for index, row in enumerate(frame.itertuples(index=False), start=1):
        code = str(getattr(row, "stock_code"))
        rank = getattr(row, "rank", index)
        try:
            result[code] = int(rank)
        except (TypeError, ValueError):
            result[code] = index
    return result


def _change_message(change_type: str, rank_delta: int | None) -> str:
    if change_type == "added":
        return "新增进入显式对比口径。"
    if change_type == "removed":
        return "从显式对比口径移出。"
    if rank_delta is None:
        return "排名发生变化。"
    direction = "上升" if rank_delta > 0 else "下降"
    return f"排名{direction} {abs(rank_delta)} 位。"


def _gate_summary(gate: pd.DataFrame) -> str:
    if gate.empty:
        return "- Gate did not run."
    counts = gate["status"].value_counts().to_dict()
    blocking_failures = gate[
        (gate["status"] == "FAIL") & (gate["severity"] == "blocking")
    ]
    return (
        f"- PASS: {int(counts.get('PASS', 0))}\n"
        f"- WARN: {int(counts.get('WARN', 0))}\n"
        f"- FAIL: {int(counts.get('FAIL', 0))}\n"
        f"- blocking_failures: {len(blocking_failures)}"
    )


def _artifact_ids(item: Mapping[str, Any]) -> str:
    rows = item.get("artifact_rows", [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ""
    artifact_ids = [
        stringify(row.get("artifact_id"))
        for row in rows
        if isinstance(row, Mapping) and row.get("artifact_id")
    ]
    return "; ".join(artifact_ids)


def _changes_note(changes: pd.DataFrame, *, metadata: Mapping[str, Any]) -> str:
    if changes.empty:
        compare_note = stringify(metadata.get("compare_note"))
        if compare_note:
            return f"- {compare_note}"
        has_compare = bool(metadata.get("compare_scan_run_id") or metadata.get("compare_score_run_id"))
        if has_compare:
            return "- 已传入显式对比产物，未发现新增 / 移出 / 排名变化。"
        return "- 未传入显式对比日或显式对比产物，未执行新增 / 移出 / 排名变化比较。"
    counts = changes["change_type"].value_counts().to_dict()
    return (
        f"- added: {int(counts.get('added', 0))}\n"
        f"- removed: {int(counts.get('removed', 0))}\n"
        f"- rank_changed: {int(counts.get('rank_changed', 0))}"
    )


def _validation_gate_note(validation_gate_summary: pd.DataFrame) -> str:
    if validation_gate_summary.empty:
        return "- validation_gate.csv 未找到或为空。"
    rows = []
    for row in validation_gate_summary.itertuples(index=False):
        rows.append(f"{stringify(row.validation_status)}={stringify(row.factor_count)}")
    return "- " + "; ".join(rows)


def _watchlist_note(watchlist_summary: pd.DataFrame, *, metadata: Mapping[str, Any]) -> str:
    if watchlist_summary.empty:
        if metadata.get("watchlist_file"):
            return "- watchlist 文件已传入，但未解析出股票代码。"
        return "- 未传入 watchlist；本节为空。"
    in_candidate = int(watchlist_summary["in_candidate_top_n"].fillna(False).astype(bool).sum())
    in_score = int(watchlist_summary["in_score_top_n"].fillna(False).astype(bool).sum())
    return (
        f"- watchlist_count: {len(watchlist_summary)}\n"
        f"- in_candidate_top_n: {in_candidate}\n"
        f"- in_score_top_n: {in_score}"
    )


def _risk_filter_rows(risk_summary: pd.DataFrame) -> pd.DataFrame:
    if risk_summary.empty:
        return pd.DataFrame(columns=DAILY_RISK_COLUMNS)
    return risk_summary[risk_summary["source_type"].isin(["hard_filter", "score_risk"])].reset_index(
        drop=True
    )


def _risk_evidence_rows(risk_summary: pd.DataFrame) -> pd.DataFrame:
    if risk_summary.empty:
        return pd.DataFrame(columns=DAILY_RISK_COLUMNS)
    return risk_summary[
        risk_summary["source_type"].isin(["announcement", "risk_event"])
    ].reset_index(drop=True)


def _top_n(metadata: Mapping[str, Any]) -> int:
    return _int_value(metadata.get("top_n"), 20)


def _row_lookup(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty or "stock_code" not in frame.columns:
        return {}
    result: dict[str, dict[str, object]] = {}
    for row in frame.to_dict("records"):
        code = stringify(row.get("stock_code"))
        if code and code not in result:
            result[code] = row
    return result


def _risk_lookup(risk_summary: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if risk_summary.empty or "stock_code" not in risk_summary.columns:
        return {}
    return {
        str(code): group.reset_index(drop=True)
        for code, group in risk_summary.groupby(risk_summary["stock_code"].astype(str), sort=False)
    }


def _dedupe_codes(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value).strip()
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return result


def _int_value(value: object, default: int) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_non_empty(*values: object) -> object | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return int(row[0]) > 0
