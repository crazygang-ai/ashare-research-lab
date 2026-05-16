from __future__ import annotations

import json
from pathlib import Path

from ashare.audit.manifest import MANIFEST_KEYS, build_manifest, write_manifest


def test_manifest_key_order_and_required_fields(tmp_path: Path) -> None:
    manifest = build_manifest(
        run_id="run",
        run_mode="exploratory",
        command="scan",
        argv=["ashare", "scan"],
        db_path="data/processed/test.duckdb",
        as_of_date="2026-06-26",
        source_run_id="factors",
        status="failed",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        config_hash="abc",
        data_snapshot_id="fingerprint:def",
        git={"sha": "abc", "worktree_clean": False, "dirty_files": ["x"]},
        inputs=[],
        artifacts=[],
        warnings=["dirty"],
        error="boom",
        overwrite_run=False,
    )
    path = tmp_path / "run_manifest.json"
    write_manifest(path, manifest)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert list(loaded) == MANIFEST_KEYS
    assert loaded["schema_version"] == "phase5.run_manifest.v1"
    assert loaded["status"] == "failed"
    assert loaded["error"] == "boom"
