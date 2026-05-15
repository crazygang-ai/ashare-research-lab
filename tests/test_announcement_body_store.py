from datetime import datetime
from pathlib import Path

from ashare.announcements.body_store import (
    announcement_text_hash,
    normalize_announcement_text,
    write_announcement_body,
)


def test_normalize_announcement_text_is_stable_for_bom_unicode_newlines_and_whitespace() -> None:
    text = "\ufeffＡ股\r\n  公告\t正文\n\n净利润  100％ "

    normalized = normalize_announcement_text(text)

    assert normalized == "A股 公告 正文 净利润 100%"
    assert normalize_announcement_text(normalized) == normalized
    assert announcement_text_hash(text) == announcement_text_hash(normalized)


def test_write_announcement_body_uses_normalized_text_and_path(tmp_path: Path) -> None:
    path = write_announcement_body(
        raw_output_dir=tmp_path,
        source_tag="phase2-fixture",
        stock_code="000001.SZ",
        publish_time=datetime(2026, 1, 5, 18, 0),
        announcement_id="ann-1",
        body_text="正文\r\n  内容",
    )

    assert path == tmp_path / "phase2-fixture" / "000001.SZ" / "2026-01-05" / "ann-1.txt"
    assert path.read_text(encoding="utf-8") == "正文 内容"
