from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest

from ashare.audit.run_store import (
    DuplicateRunError,
    begin_run,
    complete_run,
    delete_run,
    ensure_audit_schema,
    get_run,
    insert_artifacts,
    insert_inputs,
    list_runs,
)


def test_run_store_create_complete_duplicate_and_overwrite() -> None:
    connection = duckdb.connect(":memory:")
    ensure_audit_schema(connection)
    started = datetime.now(timezone.utc)

    begin_run(
        connection,
        run_id="run",
        as_of_date="2026-06-26",
        params={"command": "scan"},
        config_hash="cfg",
        data_snapshot_id=None,
        git_sha="sha",
        worktree_clean=True,
        started_at=started,
        overwrite=False,
    )
    with pytest.raises(DuplicateRunError):
        begin_run(
            connection,
            run_id="run",
            as_of_date="2026-06-26",
            params={},
            config_hash=None,
            data_snapshot_id=None,
            git_sha=None,
            worktree_clean=None,
            started_at=started,
            overwrite=False,
        )

    insert_inputs(
        connection,
        [
            {
                "input_id": "input",
                "run_id": "run",
                "input_kind": "cli_param",
                "input_ref": "source_run_id:x",
                "source_run_id": "x",
                "sha256": None,
                "row_count": None,
                "metadata": {},
                "created_at": started,
            }
        ],
    )
    insert_artifacts(
        connection,
        [
            {
                "artifact_id": "artifact",
                "run_id": "run",
                "artifact_kind": "scan",
                "role": "manifest",
                "path": "data/reports/generated/scan/run/run_manifest.json",
                "media_type": "application/json",
                "sha256": "hash",
                "row_count": None,
                "size_bytes": 10,
                "metadata": {},
                "created_at": started,
            }
        ],
    )
    complete_run(
        connection,
        run_id="run",
        status="succeeded",
        params={"command": "scan"},
        config_hash="cfg",
        data_snapshot_id="fingerprint:1",
        finished_at=datetime.now(timezone.utc),
        error=None,
    )

    stored = get_run(connection, "run")
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.finished_at is not None
    assert list_runs(connection)[0].run_id == "run"

    delete_run(connection, "run")
    assert get_run(connection, "run") is None
