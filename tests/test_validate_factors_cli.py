from __future__ import annotations

from pathlib import Path
import subprocess

import duckdb
import pandas as pd
import pytest

from ashare.fixtures.builder import INDEX_CODE, build_fixtures
from ashare.ingest.local import ingest_local
from ashare.storage.db import default_schema_path
from ashare.storage.universe_snapshots import write_factor_run_universe
from ashare.validation.runner import validate_factors


SOURCE_RUN_ID = "cli-validation"


@pytest.fixture(scope="module")
def validation_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("validate_factors_cli")
    input_dir = tmp_path / "fixtures"
    db_path = tmp_path / "ashare.duckdb"
    build_fixtures(input_dir)
    ingest_local(input_dir=input_dir, db_path=db_path)
    _run_ashare(
        [
            "calculate-factors",
            "--db-path",
            str(db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
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


def _audit_config_without_clean_worktree_gate(tmp_path: Path) -> Path:
    path = tmp_path / "audit.yaml"
    artifact_root = tmp_path / "reports"
    path.write_text(
        f"""
version: phase5.v1
run_tracking:
  formal_requires_clean_worktree: false
artifacts:
  default_root: {artifact_root.as_posix()}
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _build_current_snapshot_validation_db(db_path: Path) -> None:
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(default_schema_path().read_text(encoding="utf-8"))
        connection.executemany(
            "INSERT INTO trading_calendar (trade_date, is_open, source) VALUES (?, true, 'fixture')",
            [("2026-01-02",), ("2026-01-05",)],
        )
        connection.executemany(
            """
            INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor, source)
            VALUES (?, ?, ?, 1.0, 'fixture')
            """,
            [
                ("A", "2026-01-02", 10.0),
                ("A", "2026-01-05", 11.0),
            ],
        )
        connection.execute(
            """
            INSERT INTO factor_values
            VALUES ('A', DATE '2026-01-02', 'return_20d', 1.0, DATE '2026-01-02', 'run')
            """
        )
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=pd.Timestamp("2026-01-02").date(),
            as_of_date=pd.Timestamp("2026-01-02").date(),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL"],
                    "stock_code": ["A"],
                    "source": ["fixture"],
                    "source_tag": ["fixture"],
                    "universe_kind": ["current_snapshot"],
                }
            ),
            data_source="fixture",
        )
    finally:
        connection.close()


def _build_mismatched_snapshot_source_validation_db(db_path: Path) -> None:
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(default_schema_path().read_text(encoding="utf-8"))
        connection.executemany(
            "INSERT INTO trading_calendar (trade_date, is_open, source) VALUES (?, true, 'prices-vendor')",
            [("2026-01-02",), ("2026-01-05",)],
        )
        connection.executemany(
            """
            INSERT INTO daily_prices (stock_code, trade_date, close, adj_factor, source)
            VALUES (?, ?, ?, 1.0, 'prices-vendor')
            """,
            [
                ("A", "2026-01-02", 10.0),
                ("A", "2026-01-05", 11.0),
            ],
        )
        connection.execute(
            """
            INSERT INTO factor_values
            VALUES ('A', DATE '2026-01-02', 'return_20d', 1.0, DATE '2026-01-02', 'run')
            """
        )
        write_factor_run_universe(
            connection,
            source_run_id="run",
            trade_date=pd.Timestamp("2026-01-02").date(),
            as_of_date=pd.Timestamp("2026-01-02").date(),
            index_code="LOCAL",
            universe=pd.DataFrame(
                {
                    "index_code": ["LOCAL"],
                    "stock_code": ["A"],
                    "source": ["universe-vendor"],
                    "source_tag": ["universe-vendor"],
                    "universe_kind": ["historical_pit"],
                }
            ),
            data_source="universe-vendor",
        )
    finally:
        connection.close()


def test_validate_factors_function_returns_non_empty_fixture_results(
    validation_db_path: Path,
) -> None:
    connection = duckdb.connect(str(validation_db_path), read_only=True)
    try:
        result = validate_factors(
            connection=connection,
            start_date="2026-03-30",
            end_date="2026-05-29",
            source_run_id=SOURCE_RUN_ID,
            factor_names=["return_20d", "pe_ttm_percentile"],
            horizons=[5, 20],
        )
    finally:
        connection.close()

    assert not result.coverage.empty
    assert not result.label_summary.empty
    assert not result.rank_ic.empty
    assert not result.decay_curve.empty
    assert {"factor_name", "horizon"}.issubset(result.decay_curve.columns)


def test_validate_factors_cli_runs_and_cli_flags_override_yaml(
    validation_db_path: Path,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(
        """
single_factor:
  horizons: [60]
  n_groups: 5
  min_ic_observations: 3
  min_group_size: 1
  require_same_as_of_trade_date: true
  universe_factor_names: [is_st, is_suspended, is_delisted, low_liquidity]
  label:
    price: adjusted_close
    return_type: close_to_close
""".lstrip(),
        encoding="utf-8",
    )

    result = _run_ashare(
        [
            "validate-factors",
            "--db-path",
            str(validation_db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
            "--source-run-id",
            SOURCE_RUN_ID,
            "--factor",
            "return_20d",
            "--factor",
            "pe_ttm_percentile",
            "--horizon",
            "5,20",
            "--n-groups",
            "2",
            "--validation-config",
            str(config_path),
        ]
    )

    assert "Validation interval: 2026-03-30 to 2026-05-29" in result.stdout
    assert f"source_run_id: {SOURCE_RUN_ID}" in result.stdout
    assert "factors:" in result.stdout
    assert "return_20d" in result.stdout
    assert "pe_ttm_percentile" in result.stdout
    assert "horizons: 5, 20" in result.stdout
    assert "n_groups: 2" in result.stdout
    assert "label_summary:" in result.stdout
    assert "valid_label_count" in result.stdout
    assert "latest_usable_signal_date" in result.stdout
    assert "coverage_summary:" in result.stdout
    assert "ic_summary:" in result.stdout
    assert "group_return_summary:" in result.stdout
    assert "decay_curve:" in result.stdout
    assert "yearly_ic_summary:" in result.stdout
    assert "long_short_return is for factor analysis only" in result.stdout


def test_validate_factors_cli_requires_source_run_id(validation_db_path: Path) -> None:
    result = _run_ashare(
        [
            "validate-factors",
            "--db-path",
            str(validation_db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "source-run-id" in result.stderr


def test_formal_validate_factors_cli_rejects_current_snapshot_universe(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "validation.duckdb"
    _build_current_snapshot_validation_db(db_path)

    result = _run_ashare(
        [
            "validate-factors",
            "--db-path",
            str(db_path),
            "--from",
            "2026-01-02",
            "--to",
            "2026-01-02",
            "--source-run-id",
            "run",
            "--factor",
            "return_20d",
            "--horizon",
            "1",
            "--index-code",
            "LOCAL",
            "--data-source",
            "fixture",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "historical PIT universe" in result.stderr
    assert "current_snapshot" in result.stderr


def test_formal_factor_validation_report_rejects_current_snapshot_universe(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "report.duckdb"
    _build_current_snapshot_validation_db(db_path)

    result = _run_ashare(
        [
            "report",
            "--kind",
            "factor-validation",
            "--db-path",
            str(db_path),
            "--from",
            "2026-01-02",
            "--to",
            "2026-01-02",
            "--source-run-id",
            "run",
            "--factor",
            "return_20d",
            "--horizon",
            "1",
            "--index-code",
            "LOCAL",
            "--data-source",
            "fixture",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
            "--output-dir",
            str(tmp_path / "report-output"),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "historical PIT universe" in result.stderr
    assert "current_snapshot" in result.stderr


def test_formal_validate_factors_cli_rejects_snapshot_source_tag_mismatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "validation_mixed_source.duckdb"
    _build_mismatched_snapshot_source_validation_db(db_path)

    result = _run_ashare(
        [
            "validate-factors",
            "--db-path",
            str(db_path),
            "--from",
            "2026-01-02",
            "--to",
            "2026-01-02",
            "--source-run-id",
            "run",
            "--factor",
            "return_20d",
            "--horizon",
            "1",
            "--index-code",
            "LOCAL",
            "--data-source",
            "prices-vendor",
            "--run-mode",
            "formal",
            "--audit-config",
            str(_audit_config_without_clean_worktree_gate(tmp_path)),
        ],
        check=False,
    )

    assert result.returncode != 0
    assert "source_tag" in result.stderr
    assert "prices-vendor" in result.stderr
    assert "universe-vendor" in result.stderr


def test_validate_factors_cli_does_not_create_tables_or_files(
    validation_db_path: Path,
) -> None:
    before_tables = _tables(validation_db_path)
    before_files = {
        path.relative_to(validation_db_path.parent) for path in validation_db_path.parent.rglob("*")
    }

    _run_ashare(
        [
            "validate-factors",
            "--db-path",
            str(validation_db_path),
            "--from",
            "2026-03-30",
            "--to",
            "2026-05-29",
            "--source-run-id",
            SOURCE_RUN_ID,
            "--factor",
            "return_20d",
            "--horizon",
            "5",
        ]
    )

    after_tables = _tables(validation_db_path)
    after_files = {
        path.relative_to(validation_db_path.parent) for path in validation_db_path.parent.rglob("*")
    }

    assert after_tables == before_tables
    assert after_files == before_files


def test_cli_help_lists_all_phase_commands() -> None:
    result = _run_ashare(["--help"])

    for command in [
        "ingest",
        "validate-factors",
        "event-study",
        "daily-report",
        "scan",
        "backtest",
        "report",
        "stock-report",
        "db-init",
        "ingest-local",
        "as-of",
        "calculate-factors",
    ]:
        assert command in result.stdout
