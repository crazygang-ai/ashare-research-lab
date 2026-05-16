from __future__ import annotations

from pathlib import Path

from ashare.audit.hashing import combined_file_hash, csv_row_count, media_type_for_path, sha256_file


def test_file_hash_csv_row_count_and_media_type(tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    assert sha256_file(csv_path) == sha256_file(csv_path)
    assert csv_row_count(csv_path) == 2
    assert media_type_for_path(csv_path) == "text/csv"
    assert media_type_for_path(tmp_path / "report.md") == "text/markdown"


def test_combined_file_hash_is_order_stable(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    assert combined_file_hash([first, second]) == combined_file_hash([second, first])
