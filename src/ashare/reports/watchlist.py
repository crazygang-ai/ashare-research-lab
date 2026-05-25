"""Watchlist file parsing for personal research reports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
import re


def load_watchlist_codes(path: str | Path) -> list[str]:
    """Load stock codes from a simple text file or CSV watchlist."""
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"watchlist file does not exist: {resolved}")

    lines = [
        line.strip()
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"watchlist file is empty: {resolved}")

    if _looks_like_csv(resolved, lines):
        codes = _codes_from_csv_lines(lines)
    else:
        codes = [_first_token(line) for line in lines]
    result = _dedupe(code for code in codes if code)
    if not result:
        raise ValueError(f"watchlist file contains no stock_code values: {resolved}")
    return result


def stock_code_slug(stock_code: str) -> str:
    """Return a filesystem-friendly stock code fragment."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stock_code.strip()).strip("-")
    return slug or "stock"


def _looks_like_csv(path: Path, lines: list[str]) -> bool:
    return path.suffix.lower() == ".csv" or any("," in line for line in lines[:3])


def _codes_from_csv_lines(lines: list[str]) -> list[str]:
    rows = list(csv.reader(lines))
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    has_header = "stock_code" in header
    code_index = header.index("stock_code") if has_header else 0
    data_rows = rows[1:] if has_header else rows
    codes: list[str] = []
    for row in data_rows:
        if not row or code_index >= len(row):
            continue
        value = row[code_index].strip()
        if value and not value.startswith("#"):
            codes.append(value)
    return codes


def _first_token(line: str) -> str:
    return re.split(r"[\s,]+", line.strip(), maxsplit=1)[0].strip()


def _dedupe(codes: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in codes:
        code = str(item).strip()
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return result
