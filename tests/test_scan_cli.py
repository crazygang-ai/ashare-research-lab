from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local
from ashare.storage.db import init_db


SOURCE_RUN_ID = "scan-cli"


@pytest.fixture(scope="module")
def scan_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("scan_cli")
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(db_path),
            "--as-of",
            "2026-06-26",
            "--index-code",
            INDEX_CODE,
            "--source-run-id",
            SOURCE_RUN_ID,
        ]
    )
    return db_path


def _run_ashare(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ashare", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _tables(db_path: Path) -> set[str]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()


def _factor_values_count(db_path: Path) -> int:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0])
    finally:
        connection.close()


def test_scan_cli_generates_candidates_and_does_not_write_db(
    scan_db_path: Path,
    tmp_path: Path,
) -> None:
    before_tables = _tables(scan_db_path)
    before_factor_values = _factor_values_count(scan_db_path)
    output_dir = tmp_path / "scan"

    result = _run_ashare(
        [
            "scan",
            "--db-path",
            str(scan_db_path),
            "--as-of",
            "2026-06-26",
            "--source-run-id",
            SOURCE_RUN_ID,
            "--sort-factor",
            "return_20d",
            "--factor",
            "return_20d",
            "--factor",
            "pe_ttm_percentile",
            "--factor",
            "revenue_yoy",
            "--top",
            "3",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert "candidate list is for research only" in result.stdout
    assert "candidates.csv" in result.stdout
    assert (output_dir / "candidates.csv").exists()
    assert (output_dir / "candidate_list.md").exists()

    candidates = pd.read_csv(output_dir / "candidates.csv")
    assert len(candidates) <= 3
    expected_columns = [
        "rank",
        "stock_code",
        "stock_name",
        "industry_l1",
        "industry_l2",
        "as_of_date",
        "source_run_id",
        "sort_factor",
        "sort_factor_value",
        "factor__return_20d",
        "factor__pe_ttm_percentile",
        "factor__revenue_yoy",
        "hard_filter__is_st",
        "hard_filter__is_suspended",
        "hard_filter__is_delisted",
        "hard_filter__low_liquidity",
        "selection_reason",
        "risk_tips",
    ]
    assert list(candidates.columns) == expected_columns
    for forbidden in ["score", "total_score", "composite_score"]:
        assert forbidden not in candidates.columns
    if not candidates.empty:
        assert candidates["rank"].tolist() == sorted(candidates["rank"].tolist())
        assert candidates["selection_reason"].str.contains("return_20d").all()
        assert candidates["risk_tips"].notna().all()

    markdown = (output_dir / "candidate_list.md").read_text(encoding="utf-8")
    assert "candidate list is for research only" in markdown
    assert "综合评分" in markdown
    assert "组合回测" in markdown
    assert "风险" in markdown or "risk" in markdown

    assert _tables(scan_db_path) == before_tables
    assert _factor_values_count(scan_db_path) == before_factor_values


def test_scan_cli_no_input_is_non_zero(scan_db_path: Path, tmp_path: Path) -> None:
    result = _run_ashare(
        [
            "scan",
            "--db-path",
            str(scan_db_path),
            "--as-of",
            "2026-06-26",
            "--source-run-id",
            "missing-run",
            "--sort-factor",
            "return_20d",
            "--output-dir",
            str(tmp_path / "missing"),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "No scanable factor_values input" in result.stderr


def test_scan_cli_empty_after_filters_succeeds_with_warning(tmp_path: Path) -> None:
    db_path = tmp_path / "empty_candidates.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.executemany(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("A", date(2026, 1, 2), "return_20d", 0.5, date(2026, 1, 2), "filtered"),
                ("A", date(2026, 1, 2), "is_st", 1.0, date(2026, 1, 2), "filtered"),
            ],
        )
    finally:
        connection.close()

    output_dir = tmp_path / "empty"
    result = _run_ashare(
        [
            "scan",
            "--db-path",
            str(db_path),
            "--as-of",
            "2026-01-02",
            "--source-run-id",
            "filtered",
            "--sort-factor",
            "return_20d",
            "--factor",
            "return_20d",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert "WARNING: No candidates remained" in result.stdout
    candidates = pd.read_csv(output_dir / "candidates.csv")
    assert candidates.empty
    assert list(candidates.columns) == [
        "rank",
        "stock_code",
        "stock_name",
        "industry_l1",
        "industry_l2",
        "as_of_date",
        "source_run_id",
        "sort_factor",
        "sort_factor_value",
        "factor__return_20d",
        "hard_filter__is_st",
        "hard_filter__is_suspended",
        "hard_filter__is_delisted",
        "hard_filter__low_liquidity",
        "selection_reason",
        "risk_tips",
    ]
    text = (output_dir / "candidate_list.md").read_text(encoding="utf-8")
    assert "candidate list is for research only" in text
