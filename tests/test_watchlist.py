from __future__ import annotations

from pathlib import Path
import subprocess

from ashare.reports.watchlist import load_watchlist_codes, stock_code_slug


def test_load_watchlist_codes_reads_text_comments_and_deduplicates(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text(
        """
# personal notes stay outside committed real watchlists
002594.SZ

600519.SH review
002594.SZ duplicate
""".lstrip(),
        encoding="utf-8",
    )

    assert load_watchlist_codes(path) == ["002594.SZ", "600519.SH"]
    assert stock_code_slug("002594.SZ") == "002594-SZ"


def test_private_watchlist_files_are_ignored_but_example_is_trackable() -> None:
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "--stdin",
        ],
        input="configs/watchlist.csv\nconfigs/watchlist.local.csv\nconfigs/watchlist.txt\n",
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 0
    assert "configs/watchlist.csv" in ignored.stdout
    assert "configs/watchlist.local.csv" in ignored.stdout
    assert "configs/watchlist.txt" in ignored.stdout

    example = subprocess.run(
        ["git", "check-ignore", "configs/watchlist.example.csv"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert example.returncode == 1
