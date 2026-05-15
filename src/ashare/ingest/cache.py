"""Parquet cache helpers for market data ingest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CacheKey:
    """Stable cache address for one source/dataset/request tuple."""

    source: str
    dataset: str
    params_hash: str


def build_params_hash(
    source: str,
    dataset: str,
    params: Mapping[str, object],
) -> str:
    """Build the mandated stable SHA1 request hash."""
    payload = {
        "source": source,
        "dataset": dataset,
        "params": params,
    }
    return hashlib.sha1(
        json.dumps(
            payload,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def read_cached_frame(cache_dir: str | Path, key: CacheKey) -> pd.DataFrame | None:
    """Return a cached frame, or ``None`` when the Parquet file is absent."""
    path = _parquet_path(cache_dir, key)
    if not path.is_file():
        return None
    return pd.read_parquet(path)


def write_cached_frame(
    cache_dir: str | Path,
    key: CacheKey,
    frame: pd.DataFrame,
    metadata: Mapping[str, object],
) -> Path:
    """Write a frame and sidecar JSON metadata under the mandated cache path."""
    parquet_path = _parquet_path(cache_dir, key)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)

    sidecar = dict(metadata)
    sidecar.setdefault("source", key.source)
    sidecar.setdefault("dataset", key.dataset)
    sidecar.setdefault("params_hash", key.params_hash)
    sidecar.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
    sidecar.setdefault("row_count", int(len(frame)))
    sidecar.setdefault("columns", [str(column) for column in frame.columns])

    _json_path(cache_dir, key).write_text(
        json.dumps(_jsonable(sidecar), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return parquet_path


def _parquet_path(cache_dir: str | Path, key: CacheKey) -> Path:
    return Path(cache_dir) / key.source / key.dataset / f"{key.params_hash}.parquet"


def _json_path(cache_dir: str | Path, key: CacheKey) -> Path:
    return Path(cache_dir) / key.source / key.dataset / f"{key.params_hash}.json"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
