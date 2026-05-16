"""Artifact index record builders."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ashare.audit.hashing import csv_row_count, file_size, media_type_for_path, sha256_file


ROLE_BY_KIND_AND_KEY: dict[str, dict[str, str]] = {
    "scan": {"markdown": "markdown_report", "csv": "candidates_csv"},
    "scoring": {
        "markdown": "markdown_report",
        "scored_candidates": "scored_candidates_csv",
        "score_breakdown": "score_breakdown_csv",
        "factor_normalized_scores": "factor_normalized_scores_csv",
        "hard_filter_exclusions": "hard_filter_exclusions_csv",
        "validation_gate": "validation_gate_csv",
        "weight_sensitivity": "weight_sensitivity_csv",
        "yearly_stability": "yearly_stability_csv",
        "metadata": "metadata_json",
    },
    "backtest": {
        "markdown": "markdown_report",
        "equity_curve": "equity_curve_csv",
        "benchmark_returns": "benchmark_returns_csv",
        "rebalance_summary": "rebalance_summary_csv",
        "target_weights": "target_weights_csv",
        "holdings": "holdings_csv",
        "trade_ledger": "trade_ledger_csv",
        "metrics": "metrics_csv",
        "assumptions": "assumptions_csv",
    },
    "factor_validation": {
        "markdown": "markdown_report",
        "coverage": "coverage_csv",
        "label_summary": "label_summary_csv",
        "rank_ic": "rank_ic_csv",
        "ic_summary": "ic_summary_csv",
        "group_returns": "group_returns_csv",
        "decay_curve": "decay_curve_csv",
    },
    "event_study": {
        "markdown": "markdown_report",
        "event_samples": "event_samples_csv",
        "event_window_returns": "event_window_returns_csv",
        "event_summary": "event_summary_csv",
    },
    "announcement_parse": {
        "summary": "metadata_json",
    },
}


def build_artifact_record(
    *,
    repo_root: Path,
    run_id: str,
    artifact_kind: str,
    role: str,
    path: Path,
    created_at: datetime,
    metadata: Mapping[str, Any] | None = None,
    hash_file: bool = True,
    count_csv_rows: bool = True,
) -> dict[str, Any]:
    resolved = path.resolve()
    display = normalize_artifact_path(repo_root, resolved)
    return {
        "artifact_id": artifact_id(run_id, role, display),
        "run_id": run_id,
        "artifact_kind": artifact_kind,
        "role": role,
        "path": display,
        "media_type": media_type_for_path(resolved),
        "sha256": sha256_file(resolved) if hash_file and resolved.is_file() else None,
        "row_count": csv_row_count(resolved)
        if count_csv_rows and resolved.suffix.lower() == ".csv"
        else None,
        "size_bytes": file_size(resolved) if resolved.exists() else None,
        "created_at": created_at,
        "metadata": dict(metadata or {}),
    }


def artifact_records_for_paths(
    *,
    repo_root: Path,
    run_id: str,
    artifact_kind: str,
    paths: Mapping[str, Path],
    created_at: datetime,
    hash_files: bool = True,
    csv_row_count_enabled: bool = True,
) -> list[dict[str, Any]]:
    records = []
    for key, path in paths.items():
        if not path.exists() or not path.is_file():
            continue
        records.append(
            build_artifact_record(
                repo_root=repo_root,
                run_id=run_id,
                artifact_kind=artifact_kind,
                role=infer_role(artifact_kind, key, path),
                path=path,
                created_at=created_at,
                metadata={"key": key},
                hash_file=hash_files,
                count_csv_rows=csv_row_count_enabled,
            )
        )
    return records


def artifact_id(run_id: str, role: str, normalized_path: str) -> str:
    return hashlib.sha1(f"{run_id}|{role}|{normalized_path}".encode("utf-8")).hexdigest()


def infer_role(artifact_kind: str, key: str, path: Path) -> str:
    mapped = ROLE_BY_KIND_AND_KEY.get(artifact_kind, {}).get(key)
    if mapped:
        return mapped
    suffix = path.suffix.lower()
    stem = path.stem.replace("-", "_")
    if suffix == ".md":
        return "markdown_report"
    if suffix == ".json":
        return f"{stem}_json"
    if suffix == ".csv":
        return f"{stem}_csv"
    return stem


def normalize_artifact_path(repo_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()
