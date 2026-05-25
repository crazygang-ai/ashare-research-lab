"""Explicit universe snapshots for audited factor runs."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any

import duckdb
import pandas as pd


UNIVERSE_COLUMNS = [
    "source_run_id",
    "trade_date",
    "as_of_date",
    "index_code",
    "stock_code",
    "universe_source",
    "source",
    "source_tag",
    "universe_kind",
    "fingerprint",
    "created_at",
]


def write_factor_run_universe(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_run_id: str,
    trade_date: date,
    as_of_date: date,
    index_code: str | None,
    universe: pd.DataFrame,
    data_source: str | None,
    universe_source: str = "pit_universe_members",
) -> int:
    """Replace the explicit universe snapshot for one factor run/date."""
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    frame = _snapshot_frame(
        source_run_id=source_run_id,
        trade_date=trade_date,
        as_of_date=as_of_date,
        index_code=index_code,
        universe=universe,
        data_source=data_source,
        universe_source=universe_source,
    )
    connection.execute(
        """
        DELETE FROM factor_run_universe
        WHERE source_run_id = ?
          AND trade_date = ?
          AND as_of_date = ?
          AND COALESCE(index_code, '') = COALESCE(?, '')
        """,
        [source_run_id, trade_date, as_of_date, index_code],
    )
    if frame.empty:
        return 0
    connection.register("_factor_run_universe_insert", frame)
    try:
        column_sql = ", ".join(UNIVERSE_COLUMNS)
        connection.execute(
            f"""
            INSERT INTO factor_run_universe ({column_sql})
            SELECT {column_sql} FROM _factor_run_universe_insert
            """
        )
    finally:
        connection.unregister("_factor_run_universe_insert")
    return int(len(frame))


def delete_factor_run_universe_for_source_run(
    connection: duckdb.DuckDBPyConnection,
    source_run_id: str,
) -> int:
    """Delete all explicit universe rows for a factor source run."""
    count = int(
        connection.execute(
            "SELECT COUNT(*) FROM factor_run_universe WHERE source_run_id = ?",
            [source_run_id],
        ).fetchone()[0]
    )
    connection.execute("DELETE FROM factor_run_universe WHERE source_run_id = ?", [source_run_id])
    return count


def load_factor_run_universe(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_run_id: str,
    trade_date: date,
    index_code: str | None = None,
) -> pd.DataFrame:
    """Load an explicit universe snapshot for validation, scoring, or backtest."""
    params: list[Any] = [source_run_id, trade_date]
    sql = """
        SELECT
            source_run_id,
            trade_date,
            as_of_date,
            index_code,
            stock_code,
            universe_source,
            source,
            source_tag,
            universe_kind,
            fingerprint,
            created_at
        FROM factor_run_universe
        WHERE source_run_id = ?
          AND trade_date = ?
    """
    if index_code is not None:
        sql += " AND index_code = ?"
        params.append(index_code)
    sql += " ORDER BY stock_code"
    frame = connection.execute(sql, params).df()
    if frame.empty:
        return pd.DataFrame(columns=UNIVERSE_COLUMNS)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return frame


def require_factor_run_universe_data_source(
    snapshot: pd.DataFrame,
    *,
    data_source: str | None,
    context: str,
) -> None:
    """Fail fast when a formal run combines a universe snapshot with another source."""
    expected = str(data_source).strip() if data_source is not None else ""
    if snapshot.empty or not expected or expected == "legacy":
        return
    observed = _coalesced_snapshot_source_tags(snapshot)
    if observed == [expected]:
        return
    found = ", ".join(observed) if observed else "unknown"
    raise ValueError(
        f"{context} requires factor_run_universe source_tag to match "
        f"data_source={expected}; found source_tag={found}."
    )


def factor_run_universe_fingerprint(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_run_id: str,
    index_code: str | None = None,
) -> str | None:
    """Return a stable fingerprint for all universe rows attached to a factor run."""
    params: list[Any] = [source_run_id]
    sql = """
        SELECT trade_date, as_of_date, index_code, stock_code, source, source_tag, universe_kind
        FROM factor_run_universe
        WHERE source_run_id = ?
    """
    if index_code is not None:
        sql += " AND index_code = ?"
        params.append(index_code)
    sql += " ORDER BY trade_date, stock_code"
    rows = connection.execute(sql, params).fetchall()
    if not rows:
        return None
    payload = [
        {
            "trade_date": str(row[0]),
            "as_of_date": str(row[1]),
            "index_code": row[2],
            "stock_code": row[3],
            "source": row[4],
            "source_tag": row[5],
            "universe_kind": row[6],
        }
        for row in rows
    ]
    return "universe:" + _sha256_json(payload)


def _snapshot_frame(
    *,
    source_run_id: str,
    trade_date: date,
    as_of_date: date,
    index_code: str | None,
    universe: pd.DataFrame,
    data_source: str | None,
    universe_source: str,
) -> pd.DataFrame:
    if universe.empty or "stock_code" not in universe.columns:
        return pd.DataFrame(columns=UNIVERSE_COLUMNS)
    members = universe.dropna(subset=["stock_code"]).drop_duplicates("stock_code").copy()
    members = members.sort_values("stock_code", kind="mergesort").reset_index(drop=True)
    source_values = _unique_values(members, "source")
    source_tag_values = _unique_values(members, "source_tag")
    universe_kind_values = _unique_values(members, "universe_kind")
    fingerprint = _sha256_json(
        {
            "source_run_id": source_run_id,
            "trade_date": trade_date.isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "index_code": index_code,
            "stock_codes": members["stock_code"].astype(str).tolist(),
            "source": source_values,
            "source_tag": source_tag_values,
            "universe_kind": universe_kind_values,
        }
    )
    rows = []
    for row in members.itertuples(index=False):
        rows.append(
            {
                "source_run_id": source_run_id,
                "trade_date": trade_date,
                "as_of_date": as_of_date,
                "index_code": index_code,
                "stock_code": str(row.stock_code),
                "universe_source": universe_source,
                "source": getattr(row, "source", None) or data_source,
                "source_tag": getattr(row, "source_tag", None) or data_source,
                "universe_kind": getattr(row, "universe_kind", None) or "unknown",
                "fingerprint": "universe:" + fingerprint,
                "created_at": datetime.now(timezone.utc),
            }
        )
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


def _unique_values(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return []
    return sorted(str(value) for value in frame[column].dropna().unique().tolist())


def _coalesced_snapshot_source_tags(frame: pd.DataFrame) -> list[str]:
    values: set[str] = set()
    for _, row in frame.iterrows():
        source_tag = _clean_source_value(row.get("source_tag"))
        source = _clean_source_value(row.get("source"))
        values.add(source_tag or source or "unknown")
    return sorted(values)


def _clean_source_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _sha256_json(value: object) -> str:
    material = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
