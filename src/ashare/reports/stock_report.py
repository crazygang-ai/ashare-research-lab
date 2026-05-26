"""Phase 7 single-stock research review report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ashare.pit.asof import (
    DateLike,
    parse_as_of_date,
    query_industry_classifications_as_of,
    query_securities_as_of,
    query_universe_members_as_of,
)
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
from ashare.scan.candidates import HARD_FILTER_NAMES


STOCK_REPORT_FILES = {
    "markdown": "stock_report.md",
    "stock_factor_values": "stock_factor_values.csv",
    "stock_score_breakdown": "stock_score_breakdown.csv",
    "stock_risk_flags": "stock_risk_flags.csv",
    "stock_recent_announcements": "stock_recent_announcements.csv",
    "stock_metadata": "stock_metadata.json",
}

STOCK_RISK_COLUMNS = [
    "source_type",
    "stock_code",
    "evidence_date",
    "evidence_type",
    "severity",
    "summary",
    "evidence_id",
]

STOCK_ANNOUNCEMENT_COLUMNS = [
    "announcement_id",
    "source",
    "source_tag",
    "stock_code",
    "title",
    "announcement_type",
    "publish_time",
    "effective_date",
    "summary",
    "evidence_text",
    "confidence",
    "url",
]


@dataclass(frozen=True)
class StockReportResult:
    markdown: str
    stock_factor_values: pd.DataFrame
    stock_score_breakdown: pd.DataFrame
    stock_risk_flags: pd.DataFrame
    stock_recent_announcements: pd.DataFrame
    metadata: dict[str, Any]


def build_stock_report(
    connection: duckdb.DuckDBPyConnection,
    *,
    code: str,
    as_of_date: DateLike,
    source_run_id: str,
    score_bundle: ArtifactBundle,
    metadata: Mapping[str, Any],
    scan_bundle: ArtifactBundle | None = None,
    backtest_bundle: ArtifactBundle | None = None,
    event_study_bundle: ArtifactBundle | None = None,
    recent_days: int = 30,
) -> StockReportResult:
    """Build one single-stock report using PIT data and existing artifacts."""
    parsed_as_of = parse_as_of_date(as_of_date)
    stock_code = code.strip()
    if not stock_code:
        raise ValueError("--code must be non-empty.")
    score_metadata = read_artifact_json(score_bundle, "score_metadata.json")
    data_source = _first_non_empty(
        metadata.get("data_source"),
        score_metadata.get("data_source"),
    )
    source_reference = str(data_source) if data_source is not None else None
    index_code = _first_non_empty(metadata.get("index_code"), score_metadata.get("index_code"))

    factor_values = _stock_factor_values(
        connection,
        stock_code=stock_code,
        parsed_as_of=parsed_as_of,
        source_run_id=source_run_id,
    )
    score_breakdown = _stock_score_breakdown(score_bundle, stock_code)
    announcements = _stock_recent_announcements(
        connection,
        stock_code=stock_code,
        parsed_as_of=parsed_as_of,
        recent_days=recent_days,
        source_tag=None if source_reference == "legacy" else source_reference,
    )
    risk_flags = _stock_risk_flags(
        stock_code=stock_code,
        parsed_as_of=parsed_as_of,
        factor_values=factor_values,
        score_bundle=score_bundle,
        announcements=announcements,
        connection=connection,
        recent_days=recent_days,
        data_source=source_reference,
    )
    stock_metadata = _stock_metadata(
        connection,
        stock_code=stock_code,
        parsed_as_of=parsed_as_of,
        source_run_id=source_run_id,
        index_code=str(index_code) if index_code is not None else None,
        score_bundle=score_bundle,
        scan_bundle=scan_bundle,
        backtest_bundle=backtest_bundle,
        event_study_bundle=event_study_bundle,
        score_metadata=score_metadata,
        extra_metadata=dict(metadata),
    )
    markdown = render_stock_markdown(
        factor_values=factor_values,
        score_breakdown=score_breakdown,
        risk_flags=risk_flags,
        announcements=announcements,
        metadata=stock_metadata,
    )
    return StockReportResult(
        markdown=markdown,
        stock_factor_values=factor_values,
        stock_score_breakdown=score_breakdown,
        stock_risk_flags=risk_flags,
        stock_recent_announcements=announcements,
        metadata=stock_metadata,
    )


def render_stock_markdown(
    *,
    factor_values: pd.DataFrame,
    score_breakdown: pd.DataFrame,
    risk_flags: pd.DataFrame,
    announcements: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> str:
    """Render the single-stock Markdown report."""
    candidate = metadata.get("candidate_review", {})
    score = metadata.get("score_review", {})
    backtest = metadata.get("backtest_review", {})
    event = metadata.get("event_study_review", {})
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
        f"# Stock Research Report: {stringify(metadata.get('stock_code'))}",
        "",
        "## Metadata",
        "",
        f"- stock_code: {stringify(metadata.get('stock_code'))}",
        f"- stock_name: {stringify(metadata.get('stock_name'))}",
        f"- as_of_date: {stringify(metadata.get('as_of_date'))}",
        f"- industry_l1: {stringify(metadata.get('industry_l1'))}",
        f"- industry_l2: {stringify(metadata.get('industry_l2'))}",
        f"- in_target_universe: {stringify(metadata.get('in_target_universe'))}",
        f"- run_id: {stringify(metadata.get('run_id'))}",
        f"- run_mode: {stringify(metadata.get('run_mode'))}",
        f"- db_path: {stringify(metadata.get('db_path'))}",
        f"- source_run_id: {stringify(metadata.get('source_run_id'))}",
        f"- score_run_id: {stringify(metadata.get('score_run_id'))}",
        f"- config_hash: {stringify(metadata.get('config_hash'))}",
        f"- data_snapshot_id: {stringify(metadata.get('data_snapshot_id'))}",
        f"- git_sha: {stringify(metadata.get('git_sha'))}",
        f"- worktree_clean: {stringify(metadata.get('worktree_clean'))}",
        "",
        "## Candidate And Score Review",
        "",
        f"- candidate_pool_status: {stringify(candidate.get('status'))}",
        f"- candidate_rank: {stringify(candidate.get('rank'))}",
        f"- candidate_reason: {stringify(candidate.get('reason'))}",
        f"- score_status: {stringify(score.get('status'))}",
        f"- score_rank: {stringify(score.get('rank'))}",
        f"- total_score: {stringify(score.get('total_score'))}",
        f"- hard_filter_passed: {stringify(score.get('hard_filter_passed'))}",
        f"- score_reason: {stringify(score.get('selection_reason'))}",
        "",
        "## Input Artifact Ids And Run Ids",
        "",
        markdown_table(input_rows),
        "",
        "## Financial Factors",
        "",
        markdown_table(_factor_group(factor_values, ["revenue", "profit", "roe", "gross", "cash", "debt", "goodwill"])),
        "",
        "## Valuation Factors",
        "",
        markdown_table(_factor_group(factor_values, ["pe", "pb", "ps", "dividend", "mv", "percentile"])),
        "",
        "## Momentum Factors",
        "",
        markdown_table(_factor_group(factor_values, ["return", "ma", "momentum"])),
        "",
        "## Score Breakdown",
        "",
        markdown_table(score_breakdown, max_rows=80),
        "",
        "## Hard Filters And Soft Risk Tips",
        "",
        markdown_table(risk_flags, max_rows=80),
        "",
        "## Recent Announcement Evidence",
        "",
        markdown_table(announcements, max_rows=50),
        "",
        "## Recent Risk Event Evidence",
        "",
        markdown_table(_risk_source_rows(risk_flags, "risk_event"), max_rows=50),
        "",
        "## Event Study Review",
        "",
        f"- event_study_run_id: {stringify(event.get('run_id'))}",
        f"- matching_event_samples: {stringify(event.get('matching_event_samples'))}",
        f"- note: {stringify(event.get('note'))}",
        "",
        "## Recent Backtest Presence",
        "",
        f"- backtest_run_id: {stringify(backtest.get('run_id'))}",
        f"- target_weight_rows: {stringify(backtest.get('target_weight_rows'))}",
        f"- holding_rows: {stringify(backtest.get('holding_rows'))}",
        f"- note: {stringify(backtest.get('note'))}",
        "",
        "## Data Sources",
        "",
        "- Stock name, industry, universe membership, announcements, and risk events use PIT as-of queries.",
        "- score_run_id and optional scan/backtest/event-study artifacts are read-only inputs.",
        "- Current stock name, current industry, and current index membership are not used to backfill history.",
        "",
        "## Research Use Only",
        "",
        "- 本报告是研究辅助输出，不是交易指令。",
        "- It does not contain buy, sell, target price, or position-size instructions.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_stock_report(
    result: StockReportResult,
    output_dir: str | Path,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write Markdown, CSV, and JSON stock report artifacts."""
    resolved = Path(output_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    paths = {key: resolved / filename for key, filename in STOCK_REPORT_FILES.items()}
    fail_if_exists(list(paths.values()), overwrite=overwrite)
    result.stock_factor_values.to_csv(paths["stock_factor_values"], index=False)
    result.stock_score_breakdown.to_csv(paths["stock_score_breakdown"], index=False)
    result.stock_risk_flags.to_csv(paths["stock_risk_flags"], index=False)
    result.stock_recent_announcements.to_csv(paths["stock_recent_announcements"], index=False)
    write_json(paths["stock_metadata"], result.metadata)
    paths["markdown"].write_text(result.markdown, encoding="utf-8")
    return paths


def _stock_factor_values(
    connection: duckdb.DuckDBPyConnection,
    *,
    stock_code: str,
    parsed_as_of: Any,
    source_run_id: str,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        FROM factor_values
        WHERE stock_code = ?
          AND source_run_id = ?
          AND as_of_date = ?
          AND trade_date = ?
        ORDER BY factor_name
        """,
        [stock_code, source_run_id, parsed_as_of, parsed_as_of],
    ).df()
    return ordered_frame(
        frame,
        ["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date", "source_run_id"],
        ["factor_name"],
    )


def _stock_score_breakdown(score_bundle: ArtifactBundle, stock_code: str) -> pd.DataFrame:
    group = read_artifact_csv(score_bundle, "score_breakdown.csv")
    factors = read_artifact_csv(score_bundle, "factor_normalized_scores.csv")
    rows: list[dict[str, object]] = []
    if not group.empty and "stock_code" in group.columns:
        selected = group[group["stock_code"].astype(str) == stock_code]
        for row in selected.itertuples(index=False):
            rows.append(
                {
                    "detail_type": "group",
                    "score_group": getattr(row, "score_group", ""),
                    "factor_name": "",
                    "raw_factor_value": pd.NA,
                    "normalized_score": pd.NA,
                    "weighted_contribution": getattr(row, "weighted_contribution", pd.NA),
                    "group_score": getattr(row, "group_score", pd.NA),
                    "missing_factor_count": getattr(row, "missing_factor_count", pd.NA),
                    "validation_status": "",
                }
            )
    if not factors.empty and "stock_code" in factors.columns:
        selected = factors[factors["stock_code"].astype(str) == stock_code]
        for row in selected.itertuples(index=False):
            rows.append(
                {
                    "detail_type": "factor",
                    "score_group": getattr(row, "score_group", ""),
                    "factor_name": getattr(row, "factor_name", ""),
                    "raw_factor_value": getattr(row, "raw_factor_value", pd.NA),
                    "normalized_score": getattr(row, "normalized_score", pd.NA),
                    "weighted_contribution": getattr(row, "weighted_contribution", pd.NA),
                    "group_score": pd.NA,
                    "missing_factor_count": pd.NA,
                    "validation_status": getattr(row, "validation_status", ""),
                }
            )
    frame = pd.DataFrame(
        rows,
        columns=[
            "detail_type",
            "score_group",
            "factor_name",
            "raw_factor_value",
            "normalized_score",
            "weighted_contribution",
            "group_score",
            "missing_factor_count",
            "validation_status",
        ],
    )
    return ordered_frame(frame, list(frame.columns), ["detail_type", "score_group", "factor_name"])


def _stock_recent_announcements(
    connection: duckdb.DuckDBPyConnection,
    *,
    stock_code: str,
    parsed_as_of: Any,
    recent_days: int,
    source_tag: str | None,
) -> pd.DataFrame:
    if not _table_exists(connection, "announcements"):
        return pd.DataFrame(columns=STOCK_ANNOUNCEMENT_COLUMNS)
    start = parsed_as_of - timedelta(days=recent_days)
    sql = """
        SELECT announcement_id, source, source_tag, stock_code, title, announcement_type,
               publish_time, effective_date, url
        FROM announcements
        WHERE stock_code = ?
          AND CAST(publish_time AS DATE) <= ?
          AND effective_date BETWEEN ? AND ?
    """
    params: list[object] = [stock_code, parsed_as_of, start, parsed_as_of]
    if source_tag is not None:
        sql += " AND COALESCE(source_tag, source) = ?"
        params.append(source_tag)
    sql += " ORDER BY effective_date DESC, publish_time DESC, announcement_id"
    frame = connection.execute(
        sql,
        params,
    ).df()
    if frame.empty:
        return pd.DataFrame(columns=STOCK_ANNOUNCEMENT_COLUMNS)
    summary = _llm_summary_lookup(
        connection,
        frame["announcement_id"].astype(str).tolist(),
        source_tag=source_tag,
    )
    evidence = _llm_evidence_lookup(connection, frame["announcement_id"].astype(str).tolist())
    result = frame.copy()
    result["summary"] = result["announcement_id"].astype(str).map(summary).fillna("")
    result["evidence_text"] = result["announcement_id"].astype(str).map(evidence).fillna("")
    result["confidence"] = result["announcement_id"].astype(str).map(
        _llm_confidence_lookup(connection, frame["announcement_id"].astype(str).tolist())
    )
    return ordered_frame(result, STOCK_ANNOUNCEMENT_COLUMNS, ["effective_date", "announcement_id"])


def _stock_risk_flags(
    *,
    stock_code: str,
    parsed_as_of: Any,
    factor_values: pd.DataFrame,
    score_bundle: ArtifactBundle,
    announcements: pd.DataFrame,
    connection: duckdb.DuckDBPyConnection,
    recent_days: int,
    data_source: str | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    factor_lookup = {
        str(row.factor_name): row.factor_value for row in factor_values.itertuples(index=False)
    }
    for hard_filter in HARD_FILTER_NAMES:
        value = factor_lookup.get(hard_filter)
        if value is None or pd.isna(value):
            rows.append(_risk_row("hard_filter", stock_code, parsed_as_of, hard_filter, "blocking", "missing_hard_filter", ""))
        elif float(value) != 0.0:
            rows.append(_risk_row("hard_filter", stock_code, parsed_as_of, hard_filter, "blocking", f"failed_hard_filter value={value}", ""))
    score = read_artifact_csv(score_bundle, "scored_candidates.csv")
    if not score.empty and "stock_code" in score.columns:
        selected = score[score["stock_code"].astype(str) == stock_code]
        for row in selected.itertuples(index=False):
            tips = stringify(getattr(row, "risk_tips", ""))
            if tips:
                rows.append(_risk_row("score_risk", stock_code, parsed_as_of, "risk_tips", "warning", tips, ""))
    hard_exclusions = read_artifact_csv(score_bundle, "hard_filter_exclusions.csv")
    if not hard_exclusions.empty and "stock_code" in hard_exclusions.columns:
        selected = hard_exclusions[hard_exclusions["stock_code"].astype(str) == stock_code]
        for row in selected.itertuples(index=False):
            rows.append(
                _risk_row(
                    "score_hard_filter_exclusion",
                    stock_code,
                    getattr(row, "as_of_date", parsed_as_of),
                    getattr(row, "hard_filter_name", ""),
                    "blocking",
                    getattr(row, "exclusion_reason", ""),
                    "",
                )
            )
    if not announcements.empty:
        for row in announcements.itertuples(index=False):
            rows.append(
                _risk_row(
                    "announcement",
                    stock_code,
                    getattr(row, "effective_date", parsed_as_of),
                    getattr(row, "announcement_type", ""),
                    "info",
                    getattr(row, "summary", "") or getattr(row, "title", ""),
                    getattr(row, "announcement_id", ""),
                )
            )
    rows.extend(
        _risk_event_rows(
            connection,
            stock_code=stock_code,
            parsed_as_of=parsed_as_of,
            recent_days=recent_days,
            source=None if data_source == "legacy" else data_source,
        )
    )
    frame = pd.DataFrame(rows, columns=STOCK_RISK_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["source_type", "evidence_date", "evidence_type"],
            kind="mergesort",
            na_position="last",
        )
    return frame.reset_index(drop=True)


def _stock_metadata(
    connection: duckdb.DuckDBPyConnection,
    *,
    stock_code: str,
    parsed_as_of: Any,
    source_run_id: str,
    index_code: str | None,
    score_bundle: ArtifactBundle,
    scan_bundle: ArtifactBundle | None,
    backtest_bundle: ArtifactBundle | None,
    event_study_bundle: ArtifactBundle | None,
    score_metadata: Mapping[str, Any],
    extra_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    data_source = _first_non_empty(
        extra_metadata.get("data_source"),
        score_metadata.get("data_source"),
    )
    securities = query_securities_as_of(
        connection,
        parsed_as_of,
        include_delisted=True,
        stock_code=stock_code,
        source=str(data_source) if data_source is not None else None,
    )
    industries = query_industry_classifications_as_of(
        connection,
        parsed_as_of,
        stock_code=stock_code,
        source=str(data_source) if data_source is not None else None,
    )
    universe = query_universe_members_as_of(
        connection,
        parsed_as_of,
        index_code=index_code,
        stock_code=stock_code,
        source_tag=str(data_source) if data_source is not None else None,
    )
    stock_name = securities.iloc[0]["stock_name"] if not securities.empty else ""
    industry_l1 = industries.iloc[0]["industry_l1"] if not industries.empty else ""
    industry_l2 = industries.iloc[0]["industry_l2"] if not industries.empty else ""

    score_review = _score_review(score_bundle, stock_code)
    candidate_review = _candidate_review(scan_bundle, stock_code)
    return {
        "title": "Stock Research Report",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "as_of_date": parsed_as_of.isoformat(),
        "industry_l1": industry_l1,
        "industry_l2": industry_l2,
        "in_target_universe": not universe.empty,
        "index_code": index_code,
        "data_source": data_source,
        "source_run_id": source_run_id,
        "score_run_id": score_bundle.run_id,
        "scan_run_id": scan_bundle.run_id if scan_bundle else None,
        "backtest_run_id": backtest_bundle.run_id if backtest_bundle else None,
        "event_study_run_id": event_study_bundle.run_id if event_study_bundle else None,
        "score_metadata": dict(score_metadata),
        "input_artifacts": [
            bundle.to_metadata()
            for bundle in [score_bundle, scan_bundle, backtest_bundle, event_study_bundle]
            if bundle is not None
        ],
        "candidate_review": candidate_review,
        "score_review": score_review,
        "backtest_review": _backtest_review(backtest_bundle, stock_code),
        "event_study_review": _event_study_review(event_study_bundle, stock_code),
        **dict(extra_metadata),
    }


def _candidate_review(
    scan_bundle: ArtifactBundle | None,
    stock_code: str,
) -> dict[str, object]:
    if scan_bundle is None:
        return {
            "status": "not_evaluated",
            "rank": None,
            "reason": "未提供 scan_run_id，候选池复核降级为综合评分产物。",
        }
    candidates = read_artifact_csv(scan_bundle, "candidates.csv")
    if candidates.empty or "stock_code" not in candidates.columns:
        return {"status": "not_in_candidate_pool", "rank": None, "reason": "候选清单为空。"}
    selected = candidates[candidates["stock_code"].astype(str) == stock_code]
    if selected.empty:
        return {
            "status": "not_in_candidate_pool",
            "rank": None,
            "reason": "股票未出现在显式候选清单 Top N 中。",
        }
    row = selected.iloc[0].to_dict()
    return {
        "status": "in_candidate_pool",
        "rank": row.get("rank"),
        "reason": row.get("selection_reason"),
    }


def _score_review(score_bundle: ArtifactBundle, stock_code: str) -> dict[str, object]:
    score = read_artifact_csv(score_bundle, "scored_candidates.csv")
    if score.empty or "stock_code" not in score.columns:
        return {"status": "not_scored", "rank": None, "reason": "综合评分清单为空。"}
    selected = score[score["stock_code"].astype(str) == stock_code]
    if selected.empty:
        return {
            "status": "not_in_scored_top_n",
            "rank": None,
            "total_score": None,
            "hard_filter_passed": None,
            "selection_reason": "股票未出现在综合评分 Top N 中，或被 hard filter / 可用因子覆盖排除。",
        }
    row = selected.iloc[0].to_dict()
    return {
        "status": "in_scored_top_n",
        "rank": row.get("rank"),
        "total_score": row.get("total_score"),
        "hard_filter_passed": row.get("hard_filter_passed"),
        "selection_reason": row.get("selection_reason"),
    }


def _backtest_review(
    backtest_bundle: ArtifactBundle | None,
    stock_code: str,
) -> dict[str, object]:
    if backtest_bundle is None:
        return {"run_id": None, "target_weight_rows": None, "holding_rows": None, "note": "未提供 backtest_run_id。"}
    target = read_artifact_csv(backtest_bundle, "target_weights.csv")
    holdings = read_artifact_csv(backtest_bundle, "holdings.csv")
    target_rows = _stock_row_count(target, stock_code)
    holding_rows = _stock_row_count(holdings, stock_code)
    note = "股票在回测明细中出现。" if target_rows or holding_rows else "股票未在回测持仓或目标权重明细中出现。"
    return {
        "run_id": backtest_bundle.run_id,
        "target_weight_rows": target_rows,
        "holding_rows": holding_rows,
        "note": note,
    }


def _event_study_review(
    event_study_bundle: ArtifactBundle | None,
    stock_code: str,
) -> dict[str, object]:
    if event_study_bundle is None:
        return {"run_id": None, "matching_event_samples": None, "note": "未提供 event_study_run_id。"}
    samples = read_artifact_csv(event_study_bundle, "event_samples.csv")
    sample_count = _stock_row_count(samples, stock_code)
    note = "事件研究样本包含该股票。" if sample_count else "事件研究样本未包含该股票。"
    return {"run_id": event_study_bundle.run_id, "matching_event_samples": sample_count, "note": note}


def _risk_row(
    source_type: str,
    stock_code: str,
    evidence_date: object,
    evidence_type: object,
    severity: str,
    summary: object,
    evidence_id: object,
) -> dict[str, object]:
    return {
        "source_type": source_type,
        "stock_code": stock_code,
        "evidence_date": stringify(evidence_date),
        "evidence_type": stringify(evidence_type),
        "severity": severity,
        "summary": stringify(summary),
        "evidence_id": stringify(evidence_id),
    }


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


def _risk_event_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    stock_code: str,
    parsed_as_of: Any,
    recent_days: int,
    source: str | None,
) -> list[dict[str, object]]:
    if not _table_exists(connection, "risk_events"):
        return []
    start = parsed_as_of - timedelta(days=recent_days)
    sql = """
        SELECT event_id, event_type, event_date, effective_date
        FROM risk_events
        WHERE stock_code = ?
          AND CAST(publish_time AS DATE) <= ?
          AND effective_date BETWEEN ? AND ?
    """
    params: list[object] = [stock_code, parsed_as_of, start, parsed_as_of]
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY effective_date DESC, event_id"
    frame = connection.execute(
        sql,
        params,
    ).df()
    return [
        _risk_row(
            "risk_event",
            stock_code,
            getattr(row, "effective_date", parsed_as_of),
            getattr(row, "event_type", ""),
            "warning",
            f"Risk event: {getattr(row, 'event_type', '')}",
            getattr(row, "event_id", ""),
        )
        for row in frame.itertuples(index=False)
    ]


def _llm_summary_lookup(
    connection: duckdb.DuckDBPyConnection,
    announcement_ids: Sequence[str],
    source_tag: str | None = None,
) -> dict[str, str]:
    if not announcement_ids or not _table_exists(connection, "announcement_llm_results"):
        return {}
    placeholders = ", ".join("?" for _ in announcement_ids)
    sql = f"""
        SELECT announcement_id, summary
        FROM announcement_llm_results
        WHERE announcement_id IN ({placeholders})
          AND status = 'success'
    """
    params: list[object] = list(announcement_ids)
    if source_tag is not None:
        sql += " AND COALESCE(source_tag, source) = ?"
        params.append(source_tag)
    sql += " ORDER BY created_at DESC"
    frame = connection.execute(
        sql,
        params,
    ).df()
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        result.setdefault(str(row.announcement_id), stringify(row.summary))
    return result


def _llm_confidence_lookup(connection: duckdb.DuckDBPyConnection, announcement_ids: Sequence[str]) -> dict[str, float]:
    if not announcement_ids or not _table_exists(connection, "announcement_llm_results"):
        return {}
    placeholders = ", ".join("?" for _ in announcement_ids)
    frame = connection.execute(
        f"""
        SELECT announcement_id, confidence
        FROM announcement_llm_results
        WHERE announcement_id IN ({placeholders})
          AND status = 'success'
        ORDER BY created_at DESC
        """,
        list(announcement_ids),
    ).df()
    result: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        result.setdefault(str(row.announcement_id), row.confidence)
    return result


def _llm_evidence_lookup(connection: duckdb.DuckDBPyConnection, announcement_ids: Sequence[str]) -> dict[str, str]:
    if not announcement_ids or not _table_exists(connection, "announcement_llm_evidence"):
        return {}
    placeholders = ", ".join("?" for _ in announcement_ids)
    frame = connection.execute(
        f"""
        SELECT announcement_id, evidence_text
        FROM announcement_llm_evidence
        WHERE announcement_id IN ({placeholders})
        ORDER BY created_at, item_index
        """,
        list(announcement_ids),
    ).df()
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        text = stringify(row.evidence_text)
        if text and str(row.announcement_id) not in result:
            result[str(row.announcement_id)] = text
    return result


def _factor_group(factor_values: pd.DataFrame, markers: Sequence[str]) -> pd.DataFrame:
    columns = ["factor_name", "factor_value"]
    if factor_values.empty or "factor_name" not in factor_values.columns:
        return pd.DataFrame(columns=columns)
    lower_markers = tuple(marker.lower() for marker in markers)
    selected = factor_values[
        factor_values["factor_name"].astype(str).str.lower().map(
            lambda value: any(marker in value for marker in lower_markers)
        )
    ]
    return ordered_frame(selected, columns, ["factor_name"])


def _stock_row_count(frame: pd.DataFrame, stock_code: str) -> int:
    if frame.empty or "stock_code" not in frame.columns:
        return 0
    return int((frame["stock_code"].astype(str) == stock_code).sum())


def _risk_source_rows(risk_flags: pd.DataFrame, source_type: str) -> pd.DataFrame:
    if risk_flags.empty or "source_type" not in risk_flags.columns:
        return pd.DataFrame(columns=STOCK_RISK_COLUMNS)
    return risk_flags[risk_flags["source_type"].astype(str) == source_type].reset_index(drop=True)


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
