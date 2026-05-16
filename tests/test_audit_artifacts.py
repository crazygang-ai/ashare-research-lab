from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ashare.audit.artifacts import artifact_id, artifact_records_for_paths, build_artifact_record
from ashare.audit.hashing import sha256_file


def test_artifact_record_hash_role_and_row_count(tmp_path: Path) -> None:
    report = tmp_path / "candidate_list.md"
    csv = tmp_path / "candidates.csv"
    report.write_text("# Report\n", encoding="utf-8")
    csv.write_text("stock_code\n000001.SZ\n", encoding="utf-8")

    records = artifact_records_for_paths(
        repo_root=tmp_path,
        run_id="scan-run",
        artifact_kind="scan",
        paths={"markdown": report, "csv": csv},
        created_at=datetime.now(timezone.utc),
    )

    roles = {record["role"] for record in records}
    assert roles == {"markdown_report", "candidates_csv"}
    csv_record = [record for record in records if record["role"] == "candidates_csv"][0]
    assert csv_record["sha256"] == sha256_file(csv)
    assert csv_record["row_count"] == 1


def test_artifact_id_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "run_manifest.json"
    path.write_text("{}", encoding="utf-8")
    record = build_artifact_record(
        repo_root=tmp_path,
        run_id="run",
        artifact_kind="scan",
        role="manifest",
        path=path,
        created_at=datetime.now(timezone.utc),
    )

    assert record["artifact_id"] == artifact_id("run", "manifest", "run_manifest.json")
