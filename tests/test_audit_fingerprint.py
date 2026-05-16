from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from ashare.audit.fingerprint import (
    config_file_input,
    data_snapshot_id,
    duckdb_table_input,
    table_metadata_fingerprint,
)
from ashare.storage.db import init_db


def test_config_file_and_duckdb_table_fingerprints(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("version: test\n", encoding="utf-8")
    db_path = tmp_path / "db.duckdb"
    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            """
            INSERT INTO factor_values (
                stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
            )
            VALUES ('A', ?, 'return_20d', 0.1, ?, 'run')
            """,
            [date(2026, 1, 2), date(2026, 1, 2)],
        )
        created_at = datetime.now(timezone.utc)
        file_input = config_file_input(
            repo_root=tmp_path,
            run_id="audit-run",
            path=config,
            created_at=created_at,
        )
        table_input = duckdb_table_input(
            connection=connection,
            run_id="audit-run",
            table_name="factor_values",
            source_run_id="run",
            predicate="source_run_id=run",
            created_at=created_at,
        )
        metadata = table_metadata_fingerprint(
            connection,
            table_name="factor_values",
            source_run_id="run",
        )
    finally:
        connection.close()

    assert file_input["sha256"]
    assert table_input["row_count"] == 1
    assert metadata["trade_date_min"] == "2026-01-02"
    assert data_snapshot_id([file_input, table_input]).startswith("fingerprint:")
