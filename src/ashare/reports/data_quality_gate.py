"""Daily research data quality gate for Phase 7 reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ashare.audit.hashing import sha256_file
from ashare.pit.asof import (
    DateLike,
    parse_as_of_date,
    query_securities_as_of,
    query_universe_members_as_of,
)
from ashare.reports.run_summary import ArtifactBundle, fail_if_exists, jsonable, write_json
from ashare.scan.candidates import HARD_FILTER_NAMES
from ashare.storage.db import CURRENT_SCHEMA_VERSION


GATE_COLUMNS = [
    "check_name",
    "status",
    "severity",
    "observed_value",
    "threshold",
    "message",
]

DATA_QUALITY_GATE_FILES = {
    "csv": "data_quality_gate.csv",
    "json": "data_quality_gate.json",
}

DEFAULT_GATE_CONFIG: dict[str, Any] = {
    "min_price_coverage": 0.8,
    "min_valuation_coverage": 0.8,
    "min_factor_stock_coverage": 0.8,
    "min_hard_filter_coverage": 0.8,
    "allow_missing_announcements": True,
    "allow_missing_risk_events": True,
    "required_schema_version": CURRENT_SCHEMA_VERSION,
}


@dataclass(frozen=True)
class DataQualityGateResult:
    table: pd.DataFrame
    metadata: dict[str, Any]

    @property
    def has_blocking_failures(self) -> bool:
        if self.table.empty:
            return False
        failures = self.table[
            (self.table["status"] == "FAIL") & (self.table["severity"] == "blocking")
        ]
        return not failures.empty

    @property
    def summary(self) -> dict[str, int]:
        if self.table.empty:
            return {"PASS": 0, "WARN": 0, "FAIL": 0}
        counts = self.table["status"].value_counts().to_dict()
        return {status: int(counts.get(status, 0)) for status in ["PASS", "WARN", "FAIL"]}


def build_data_quality_gate(
    connection: duckdb.DuckDBPyConnection,
    *,
    as_of_date: DateLike,
    source_run_id: str,
    input_artifacts: Sequence[ArtifactBundle],
    config_paths: Sequence[Path],
    repo_root: Path,
    index_code: str | None = None,
    gate_config: Mapping[str, Any] | None = None,
) -> DataQualityGateResult:
    """Evaluate the minimum formal daily-report data quality checks."""
    parsed_as_of = parse_as_of_date(as_of_date)
    config = {**DEFAULT_GATE_CONFIG, **dict(gate_config or {})}
    rows: list[dict[str, object]] = []

    _calendar_check(connection, parsed_as_of, rows)
    universe_codes = _target_universe(connection, parsed_as_of, index_code)
    _append(
        rows,
        "target_universe",
        "PASS" if universe_codes else "FAIL",
        "blocking",
        str(len(universe_codes)),
        "> 0",
        "Target PIT universe resolved."
        if universe_codes
        else "No PIT universe or active securities were found for as_of_date.",
    )
    _coverage_check(
        connection,
        table_name="daily_prices",
        date_column="trade_date",
        parsed_as_of=parsed_as_of,
        universe_codes=universe_codes,
        min_coverage=float(config["min_price_coverage"]),
        rows=rows,
        check_name="daily_prices_coverage",
    )
    _coverage_check(
        connection,
        table_name="valuation_daily",
        date_column="trade_date",
        parsed_as_of=parsed_as_of,
        universe_codes=universe_codes,
        min_coverage=float(config["min_valuation_coverage"]),
        rows=rows,
        check_name="valuation_daily_coverage",
    )
    _factor_values_check(
        connection,
        parsed_as_of=parsed_as_of,
        source_run_id=source_run_id,
        universe_codes=universe_codes,
        min_coverage=float(config["min_factor_stock_coverage"]),
        rows=rows,
    )
    _hard_filter_check(
        connection,
        parsed_as_of=parsed_as_of,
        source_run_id=source_run_id,
        universe_codes=universe_codes,
        min_coverage=float(config["min_hard_filter_coverage"]),
        rows=rows,
    )
    _optional_table_check(
        connection,
        table_name="announcements",
        date_column="effective_date",
        parsed_as_of=parsed_as_of,
        allow_missing=bool(config["allow_missing_announcements"]),
        rows=rows,
    )
    _optional_table_check(
        connection,
        table_name="risk_events",
        date_column="effective_date",
        parsed_as_of=parsed_as_of,
        allow_missing=bool(config["allow_missing_risk_events"]),
        rows=rows,
    )
    _input_artifact_checks(input_artifacts, rows)
    _config_file_checks(config_paths, repo_root, rows)
    _schema_check(connection, int(config["required_schema_version"]), rows)

    table = pd.DataFrame(rows, columns=GATE_COLUMNS)
    metadata = {
        "as_of_date": parsed_as_of.isoformat(),
        "source_run_id": source_run_id,
        "index_code": index_code,
        "gate_config": dict(config),
        "universe_size": len(universe_codes),
    }
    return DataQualityGateResult(table=table, metadata=metadata)


def write_data_quality_gate(
    result: DataQualityGateResult,
    output_dir: str | Path,
    metadata: Mapping[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Write data quality gate CSV and JSON artifacts."""
    resolved = Path(output_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    paths = {key: resolved / filename for key, filename in DATA_QUALITY_GATE_FILES.items()}
    fail_if_exists(list(paths.values()), overwrite=overwrite)
    result.table.to_csv(paths["csv"], index=False)
    payload = {
        "metadata": {**result.metadata, **dict(metadata or {})},
        "summary": result.summary,
        "has_blocking_failures": result.has_blocking_failures,
        "checks": result.table.to_dict("records"),
    }
    write_json(paths["json"], payload)
    return paths


def _calendar_check(
    connection: duckdb.DuckDBPyConnection,
    parsed_as_of: date,
    rows: list[dict[str, object]],
) -> None:
    if not _table_exists(connection, "trading_calendar"):
        _append(
            rows,
            "trading_calendar_open",
            "FAIL",
            "blocking",
            "table_missing",
            "as_of_date open trading day",
            "trading_calendar table is missing.",
        )
        return
    row = connection.execute(
        """
        SELECT COUNT(*), COALESCE(MAX(CASE WHEN is_open THEN 1 ELSE 0 END), 0)
        FROM trading_calendar
        WHERE trade_date = ?
        """,
        [parsed_as_of],
    ).fetchone()
    row_count = int(row[0])
    is_open = int(row[1]) == 1
    _append(
        rows,
        "trading_calendar_open",
        "PASS" if row_count and is_open else "FAIL",
        "blocking",
        f"rows={row_count}; is_open={is_open}",
        "row exists and is_open=true",
        "as_of_date is an open trading day."
        if row_count and is_open
        else "as_of_date is missing from trading_calendar or is not an open trading day.",
    )


def _target_universe(
    connection: duckdb.DuckDBPyConnection,
    parsed_as_of: date,
    index_code: str | None,
) -> tuple[str, ...]:
    if _table_exists(connection, "universe_members"):
        universe = query_universe_members_as_of(
            connection,
            parsed_as_of,
            index_code=index_code,
        )
        if not universe.empty:
            return tuple(sorted(set(universe["stock_code"].astype(str))))
    if _table_exists(connection, "securities"):
        securities = query_securities_as_of(connection, parsed_as_of, include_delisted=False)
        if not securities.empty:
            return tuple(sorted(set(securities["stock_code"].astype(str))))
    return ()


def _coverage_check(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    date_column: str,
    parsed_as_of: date,
    universe_codes: Sequence[str],
    min_coverage: float,
    rows: list[dict[str, object]],
    check_name: str,
) -> None:
    if not _table_exists(connection, table_name):
        _append(
            rows,
            check_name,
            "FAIL",
            "blocking",
            "table_missing",
            f">= {min_coverage:.2%}",
            f"{table_name} table is missing.",
        )
        return
    if not universe_codes:
        _append(
            rows,
            check_name,
            "FAIL",
            "blocking",
            "0/0",
            f">= {min_coverage:.2%}",
            "Coverage cannot be evaluated because target universe is empty.",
        )
        return
    placeholders = ", ".join("?" for _ in universe_codes)
    params: list[Any] = [parsed_as_of, *universe_codes]
    covered = int(
        connection.execute(
            f"""
            SELECT COUNT(DISTINCT stock_code)
            FROM {table_name}
            WHERE {date_column} = ?
              AND stock_code IN ({placeholders})
            """,
            params,
        ).fetchone()[0]
    )
    coverage = covered / len(universe_codes)
    _append(
        rows,
        check_name,
        "PASS" if coverage >= min_coverage else "FAIL",
        "blocking",
        f"{covered}/{len(universe_codes)} ({coverage:.2%})",
        f">= {min_coverage:.2%}",
        f"{table_name} coverage for target universe is sufficient."
        if coverage >= min_coverage
        else f"{table_name} coverage is below threshold.",
    )


def _factor_values_check(
    connection: duckdb.DuckDBPyConnection,
    *,
    parsed_as_of: date,
    source_run_id: str,
    universe_codes: Sequence[str],
    min_coverage: float,
    rows: list[dict[str, object]],
) -> None:
    if not _table_exists(connection, "factor_values"):
        _append(
            rows,
            "factor_values_source_run",
            "FAIL",
            "blocking",
            "table_missing",
            "rows > 0",
            "factor_values table is missing.",
        )
        return
    row = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT stock_code), COUNT(DISTINCT factor_name)
        FROM factor_values
        WHERE source_run_id = ?
          AND as_of_date = ?
          AND trade_date = ?
        """,
        [source_run_id, parsed_as_of, parsed_as_of],
    ).fetchone()
    row_count = int(row[0])
    stock_count = int(row[1])
    factor_count = int(row[2])
    denominator = len(universe_codes)
    coverage = stock_count / denominator if denominator else 0.0
    status = "PASS" if row_count > 0 and coverage >= min_coverage else "FAIL"
    _append(
        rows,
        "factor_values_source_run",
        status,
        "blocking",
        f"rows={row_count}; stocks={stock_count}/{denominator}; factors={factor_count}",
        f"rows > 0 and stock coverage >= {min_coverage:.2%}",
        "factor_values rows exist for source_run_id and as_of_date."
        if status == "PASS"
        else "factor_values rows are missing or below coverage threshold.",
    )


def _hard_filter_check(
    connection: duckdb.DuckDBPyConnection,
    *,
    parsed_as_of: date,
    source_run_id: str,
    universe_codes: Sequence[str],
    min_coverage: float,
    rows: list[dict[str, object]],
) -> None:
    if not _table_exists(connection, "factor_values"):
        _append(
            rows,
            "hard_filter_coverage",
            "FAIL",
            "blocking",
            "table_missing",
            "all hard filters present",
            "factor_values table is missing.",
        )
        return
    if not universe_codes:
        _append(
            rows,
            "hard_filter_coverage",
            "FAIL",
            "blocking",
            "0/0",
            f">= {min_coverage:.2%}",
            "Hard filter coverage cannot be evaluated because target universe is empty.",
        )
        return
    stock_placeholders = ", ".join("?" for _ in universe_codes)
    filter_placeholders = ", ".join("?" for _ in HARD_FILTER_NAMES)
    params: list[Any] = [
        source_run_id,
        parsed_as_of,
        parsed_as_of,
        *HARD_FILTER_NAMES,
        *universe_codes,
    ]
    frame = connection.execute(
        f"""
        SELECT stock_code, COUNT(DISTINCT factor_name) AS filter_count
        FROM factor_values
        WHERE source_run_id = ?
          AND as_of_date = ?
          AND trade_date = ?
          AND factor_name IN ({filter_placeholders})
          AND stock_code IN ({stock_placeholders})
        GROUP BY stock_code
        """,
        params,
    ).df()
    complete = (
        int((frame["filter_count"] >= len(HARD_FILTER_NAMES)).sum()) if not frame.empty else 0
    )
    coverage = complete / len(universe_codes)
    _append(
        rows,
        "hard_filter_coverage",
        "PASS" if coverage >= min_coverage else "FAIL",
        "blocking",
        f"{complete}/{len(universe_codes)} ({coverage:.2%})",
        f">= {min_coverage:.2%}; filters={','.join(HARD_FILTER_NAMES)}",
        "Hard filter coverage is sufficient."
        if coverage >= min_coverage
        else "Hard filter coverage is below threshold.",
    )


def _optional_table_check(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    date_column: str,
    parsed_as_of: date,
    allow_missing: bool,
    rows: list[dict[str, object]],
) -> None:
    severity = "warning" if allow_missing else "blocking"
    if not _table_exists(connection, table_name):
        _append(
            rows,
            f"{table_name}_available",
            "WARN" if allow_missing else "FAIL",
            severity,
            "table_missing",
            "table exists or configured downgrade",
            f"{table_name} table is missing; downgrade allowed."
            if allow_missing
            else f"{table_name} table is missing.",
        )
        return
    count = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE {date_column} <= ?",
            [parsed_as_of],
        ).fetchone()[0]
    )
    if count > 0:
        _append(
            rows,
            f"{table_name}_available",
            "PASS",
            "info",
            str(count),
            "> 0",
            f"{table_name} has PIT-visible rows.",
        )
    else:
        _append(
            rows,
            f"{table_name}_available",
            "WARN" if allow_missing else "FAIL",
            severity,
            "0",
            "> 0 or configured downgrade",
            f"{table_name} has no PIT-visible rows; downgrade allowed."
            if allow_missing
            else f"{table_name} has no PIT-visible rows.",
        )


def _input_artifact_checks(
    input_artifacts: Sequence[ArtifactBundle],
    rows: list[dict[str, object]],
) -> None:
    if not input_artifacts:
        _append(
            rows,
            "input_artifacts",
            "FAIL",
            "blocking",
            "0",
            ">= 1",
            "No input artifacts were supplied to the data quality gate.",
        )
        return
    for bundle in input_artifacts:
        name = f"input_artifact_{bundle.kind}"
        if bundle.run_id is None or bundle.warnings:
            _append(
                rows,
                name,
                "FAIL",
                "blocking",
                bundle.run_id or "",
                "indexed artifact files exist",
                "; ".join(bundle.warnings) or "Input artifact could not be resolved.",
            )
            continue
        hashable = True
        for path in bundle.files.values():
            try:
                _ = sha256_file(path)
            except OSError:
                hashable = False
                break
        _append(
            rows,
            name,
            "PASS" if hashable else "FAIL",
            "blocking",
            f"run_id={bundle.run_id}; files={len(bundle.files)}",
            "all indexed files hashable",
            "Input artifact files exist and are hashable."
            if hashable
            else "At least one input artifact file cannot be hashed.",
        )


def _config_file_checks(
    config_paths: Sequence[Path],
    repo_root: Path,
    rows: list[dict[str, object]],
) -> None:
    if not config_paths:
        _append(
            rows,
            "config_files",
            "FAIL",
            "blocking",
            "0",
            ">= 1",
            "No config files were supplied to the data quality gate.",
        )
        return
    for path in config_paths:
        resolved = path if path.is_absolute() else (repo_root / path)
        try:
            digest = sha256_file(resolved)
        except OSError:
            _append(
                rows,
                f"config_file_{path.name}",
                "FAIL",
                "blocking",
                str(path),
                "exists and hashable",
                "Config file is missing or cannot be hashed.",
            )
            continue
        _append(
            rows,
            f"config_file_{path.name}",
            "PASS",
            "info",
            digest[:12],
            "exists and hashable",
            "Config file exists and is hashable.",
        )


def _schema_check(
    connection: duckdb.DuckDBPyConnection,
    required_schema_version: int,
    rows: list[dict[str, object]],
) -> None:
    required_tables = {
        "trading_calendar",
        "daily_prices",
        "valuation_daily",
        "factor_values",
        "research_runs",
        "research_run_inputs",
        "research_artifacts",
    }
    tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
    }
    missing_tables = sorted(required_tables.difference(tables))
    if missing_tables:
        _append(
            rows,
            "database_schema_tables",
            "FAIL",
            "blocking",
            ", ".join(missing_tables),
            "all required tables exist",
            "Database schema is missing required table(s).",
        )
    else:
        _append(
            rows,
            "database_schema_tables",
            "PASS",
            "info",
            str(len(required_tables)),
            "all required tables exist",
            "Required database tables exist.",
        )

    version = 0
    if "schema_version" in tables:
        row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
        version = int(row[0] or 0)
    _append(
        rows,
        "database_schema_version",
        "PASS" if version >= required_schema_version else "FAIL",
        "blocking",
        str(version),
        f">= {required_schema_version}",
        "Database schema version is current enough."
        if version >= required_schema_version
        else "Database schema version is older than required.",
    )


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


def _append(
    rows: list[dict[str, object]],
    check_name: str,
    status: str,
    severity: str,
    observed_value: object,
    threshold: object,
    message: str,
) -> None:
    if status not in {"PASS", "WARN", "FAIL"}:
        raise ValueError(f"Unsupported data quality status: {status}")
    if severity not in {"info", "warning", "blocking"}:
        raise ValueError(f"Unsupported data quality severity: {severity}")
    rows.append(
        {
            "check_name": check_name,
            "status": status,
            "severity": severity,
            "observed_value": jsonable(observed_value),
            "threshold": jsonable(threshold),
            "message": message,
        }
    )
