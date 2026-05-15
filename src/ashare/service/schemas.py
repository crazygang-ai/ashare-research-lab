"""Small response helpers shared by the Phase 4 service endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


RESEARCH_FLAGS = {
    "research_only": True,
    "not_trading_instruction": True,
}


def with_research_flags(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = dict(RESEARCH_FLAGS)
    if payload:
        result.update(payload)
    return result


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def dataframe_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): jsonable(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]
