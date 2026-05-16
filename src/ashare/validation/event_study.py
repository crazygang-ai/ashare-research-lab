"""Event-study validation over PIT-visible event samples."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Any

import duckdb
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date, query_universe_members_as_of


EVENT_SOURCES = {"announcements", "risk_events", "announcement_llm_results"}
BENCHMARKS = {"synthetic_equal_weight", "synthetic_cap_weight", "none"}
DEDUPLICATION_MODES = {"none", "same-stock-date-type"}
LLM_EVENT_TYPES = {
    "llm_sentiment_positive",
    "llm_sentiment_negative",
    "llm_risk_detected",
    "llm_catalyst_detected",
}

EVENT_SAMPLE_COLUMNS = [
    "event_source",
    "event_id",
    "stock_code",
    "event_type",
    "event_date",
    "publish_time",
    "effective_date",
    "source",
    "source_tag",
    "title",
    "included",
    "skip_reason",
    "duplicate_group_id",
    "available_max_horizon",
]

EVENT_WINDOW_RETURN_COLUMNS = [
    "event_source",
    "event_id",
    "stock_code",
    "event_type",
    "event_date",
    "horizon",
    "event_price_date",
    "future_price_date",
    "event_return",
    "benchmark_return",
    "excess_return",
]

EVENT_SUMMARY_COLUMNS = [
    "event_source",
    "event_type",
    "horizon",
    "sample_count",
    "mean_event_return",
    "median_event_return",
    "win_rate",
    "mean_benchmark_return",
    "mean_excess_return",
    "median_excess_return",
    "excess_win_rate",
    "p25_excess_return",
    "p75_excess_return",
]


@dataclass(frozen=True)
class EventStudyResult:
    """Data frames produced by one event-study run."""

    event_samples: pd.DataFrame
    event_window_returns: pd.DataFrame
    event_summary: pd.DataFrame
    warnings: tuple[str, ...] = ()


def run_event_study(
    connection: duckdb.DuckDBPyConnection,
    *,
    event_source: str,
    event_types: Sequence[str],
    start_date: DateLike,
    end_date: DateLike,
    horizons: Sequence[int],
    index_code: str | None,
    benchmark: str = "synthetic_equal_weight",
    deduplicate: str = "none",
    min_confidence: float = 0.7,
) -> EventStudyResult:
    """Run a PIT event study using a caller-owned DuckDB connection."""
    source = str(event_source)
    if source not in EVENT_SOURCES:
        raise ValueError(
            "--event-source must be one of: " + ", ".join(sorted(EVENT_SOURCES))
        )
    if benchmark not in BENCHMARKS:
        raise ValueError("--benchmark must be one of: " + ", ".join(sorted(BENCHMARKS)))
    if deduplicate not in DEDUPLICATION_MODES:
        raise ValueError(
            "--deduplicate must be one of: " + ", ".join(sorted(DEDUPLICATION_MODES))
        )
    parsed_start = parse_as_of_date(start_date)
    parsed_end = parse_as_of_date(end_date)
    if parsed_start > parsed_end:
        raise ValueError("--from must be on or before --to.")
    parsed_horizons = _normalize_horizons(horizons)
    parsed_event_types = _normalize_event_types(event_types)
    if benchmark != "none" and not index_code:
        raise ValueError("--index-code is required when --benchmark is synthetic.")
    if source == "announcement_llm_results":
        unknown = sorted(set(parsed_event_types).difference(LLM_EVENT_TYPES))
        if unknown:
            raise ValueError(
                "announcement_llm_results event types must be one of "
                f"{', '.join(sorted(LLM_EVENT_TYPES))}; unknown: {', '.join(unknown)}"
            )

    events = _load_events(
        connection=connection,
        event_source=source,
        event_types=parsed_event_types,
        start_date=parsed_start,
        end_date=parsed_end,
        min_confidence=min_confidence,
    )
    if events.empty:
        samples = _empty_samples()
        return EventStudyResult(
            event_samples=samples,
            event_window_returns=_empty_window_returns(),
            event_summary=_empty_summary(),
            warnings=("No PIT-visible event samples matched the requested filters.",),
        )

    events = _prepare_event_samples(events)
    warnings: list[str] = []
    duplicate_rows = int((events["duplicate_group_id"] != "").sum())
    if duplicate_rows:
        duplicate_groups = events.loc[
            events["duplicate_group_id"] != "", "duplicate_group_id"
        ].nunique()
        warnings.append(
            f"Detected {duplicate_rows} duplicate event rows across {duplicate_groups} "
            "same-stock-date-type group(s)."
        )

    if deduplicate == "same-stock-date-type":
        events = _apply_same_stock_date_type_deduplication(events)

    trading_dates = _open_trading_dates(connection)
    if not trading_dates:
        raise ValueError("trading_calendar has no open trading days.")
    trading_index = {trade_date: index for index, trade_date in enumerate(trading_dates)}
    price_map = _price_map(connection)
    benchmark_cache: dict[tuple[date, date, str, str | None], float] = {}
    window_rows: list[dict[str, Any]] = []

    for row_index, event in events.iterrows():
        if not bool(event["included"]):
            continue
        event_date = _as_date(event["event_date"])
        event_price = _adjusted_close(price_map.get((str(event["stock_code"]), event_date)))
        if event_price is None:
            events.loc[row_index, "included"] = False
            events.loc[row_index, "skip_reason"] = "missing_event_date_price"
            events.loc[row_index, "available_max_horizon"] = 0
            continue

        event_date_index = trading_index.get(event_date)
        if event_date_index is None:
            events.loc[row_index, "included"] = False
            events.loc[row_index, "skip_reason"] = "event_date_not_open"
            events.loc[row_index, "available_max_horizon"] = 0
            continue

        available_horizons: list[int] = []
        for horizon in parsed_horizons:
            future_index = event_date_index + horizon
            if future_index >= len(trading_dates):
                continue
            future_date = trading_dates[future_index]
            future_price = _adjusted_close(
                price_map.get((str(event["stock_code"]), future_date))
            )
            if future_price is None:
                continue
            event_return = future_price / event_price - 1.0
            benchmark_return = _cached_benchmark_return(
                connection=connection,
                cache=benchmark_cache,
                price_map=price_map,
                event_date=event_date,
                future_date=future_date,
                index_code=index_code,
                benchmark=benchmark,
            )
            excess_return = (
                event_return - benchmark_return
                if pd.notna(benchmark_return)
                else float("nan")
            )
            window_rows.append(
                {
                    "event_source": event["event_source"],
                    "event_id": event["event_id"],
                    "stock_code": event["stock_code"],
                    "event_type": event["event_type"],
                    "event_date": event_date,
                    "horizon": horizon,
                    "event_price_date": event_date,
                    "future_price_date": future_date,
                    "event_return": event_return,
                    "benchmark_return": benchmark_return,
                    "excess_return": excess_return,
                }
            )
            available_horizons.append(horizon)

        max_available = max(available_horizons) if available_horizons else 0
        events.loc[row_index, "available_max_horizon"] = max_available
        if not available_horizons:
            events.loc[row_index, "included"] = False
            events.loc[row_index, "skip_reason"] = "insufficient_future_window"

    samples = _finalize_samples(events)
    window_returns = _finalize_window_returns(pd.DataFrame(window_rows))
    summary = _summarize_window_returns(window_returns)
    warnings.extend(_skip_warnings(samples))
    if summary.empty:
        warnings.append("No event windows were generated for the requested horizons.")
    elif int(summary["sample_count"].min()) < 5:
        warnings.append("At least one event summary bucket has fewer than 5 samples.")

    return EventStudyResult(
        event_samples=samples,
        event_window_returns=window_returns,
        event_summary=summary,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _load_events(
    *,
    connection: duckdb.DuckDBPyConnection,
    event_source: str,
    event_types: tuple[str, ...],
    start_date: date,
    end_date: date,
    min_confidence: float,
) -> pd.DataFrame:
    if event_source == "announcements":
        return _load_announcement_events(connection, event_types, start_date, end_date)
    if event_source == "risk_events":
        return _load_risk_events(connection, event_types, start_date, end_date)
    return _load_llm_events(connection, event_types, start_date, end_date, min_confidence)


def _load_announcement_events(
    connection: duckdb.DuckDBPyConnection,
    event_types: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in event_types)
    return connection.execute(
        f"""
        SELECT
            'announcements' AS event_source,
            announcement_id AS event_id,
            stock_code,
            announcement_type AS event_type,
            effective_date AS event_date,
            publish_time,
            effective_date,
            source,
            source_tag,
            title
        FROM announcements
        WHERE effective_date BETWEEN ? AND ?
          AND announcement_type IN ({placeholders})
        ORDER BY effective_date, publish_time, source_tag, announcement_id
        """,
        [start_date, end_date, *event_types],
    ).df()


def _load_risk_events(
    connection: duckdb.DuckDBPyConnection,
    event_types: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in event_types)
    return connection.execute(
        f"""
        SELECT
            'risk_events' AS event_source,
            event_id,
            stock_code,
            event_type,
            effective_date AS event_date,
            publish_time,
            effective_date,
            source,
            NULL AS source_tag,
            NULL AS title
        FROM risk_events
        WHERE effective_date BETWEEN ? AND ?
          AND event_type IN ({placeholders})
        ORDER BY effective_date, publish_time, source, event_id
        """,
        [start_date, end_date, *event_types],
    ).df()


def _load_llm_events(
    connection: duckdb.DuckDBPyConnection,
    event_types: tuple[str, ...],
    start_date: date,
    end_date: date,
    min_confidence: float,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT
            r.parse_id,
            r.announcement_id,
            r.source,
            r.source_tag,
            r.stock_code,
            r.announcement_type,
            r.sentiment,
            r.parsed_json,
            r.confidence,
            a.title,
            a.publish_time,
            a.effective_date
        FROM announcement_llm_results r
        JOIN announcements a
          ON a.announcement_id = r.announcement_id
         AND (
             a.source_tag = r.source_tag
             OR a.source_tag IS NULL
             OR r.source_tag IS NULL
         )
        WHERE r.status = 'success'
          AND r.confidence >= ?
          AND a.effective_date BETWEEN ? AND ?
        ORDER BY a.effective_date, a.publish_time, r.source_tag, r.parse_id
        """,
        [float(min_confidence), start_date, end_date],
    ).df()
    if frame.empty:
        return pd.DataFrame(columns=EVENT_SAMPLE_COLUMNS[:10])

    requested = set(event_types)
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        parsed = _json_object(row.parsed_json)
        row_event_types: list[str] = []
        sentiment = str(row.sentiment or "").lower()
        if sentiment == "positive":
            row_event_types.append("llm_sentiment_positive")
        if sentiment == "negative":
            row_event_types.append("llm_sentiment_negative")
        if _json_list_non_empty(parsed.get("risks")):
            row_event_types.append("llm_risk_detected")
        if _json_list_non_empty(parsed.get("catalysts")):
            row_event_types.append("llm_catalyst_detected")

        for event_type in row_event_types:
            if event_type not in requested:
                continue
            event_id = f"{row.parse_id}:{event_type}"
            rows.append(
                {
                    "event_source": "announcement_llm_results",
                    "event_id": event_id,
                    "stock_code": row.stock_code,
                    "event_type": event_type,
                    "event_date": row.effective_date,
                    "publish_time": row.publish_time,
                    "effective_date": row.effective_date,
                    "source": row.source,
                    "source_tag": row.source_tag,
                    "title": row.title,
                }
            )
    return pd.DataFrame(rows, columns=EVENT_SAMPLE_COLUMNS[:10])


def _prepare_event_samples(events: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    for column in EVENT_SAMPLE_COLUMNS[:10]:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, EVENT_SAMPLE_COLUMNS[:10]]
    result["event_date"] = pd.to_datetime(result["event_date"]).dt.date
    result["effective_date"] = pd.to_datetime(result["effective_date"]).dt.date
    result["included"] = True
    result["skip_reason"] = ""
    result["duplicate_group_id"] = _duplicate_group_ids(result)
    result["available_max_horizon"] = pd.NA
    return result.sort_values(
        ["effective_date", "publish_time", "source_tag", "event_id"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def _duplicate_group_ids(samples: pd.DataFrame) -> pd.Series:
    keys = ["stock_code", "effective_date", "event_type"]
    counts = samples.groupby(keys, dropna=False)["event_id"].transform("count")
    values = []
    for row, count in zip(samples.itertuples(index=False), counts, strict=False):
        if int(count) <= 1:
            values.append("")
            continue
        raw = f"{row.stock_code}|{row.effective_date}|{row.event_type}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        values.append(f"dup-{digest}")
    return pd.Series(values, index=samples.index)


def _apply_same_stock_date_type_deduplication(samples: pd.DataFrame) -> pd.DataFrame:
    result = samples.sort_values(
        ["effective_date", "publish_time", "source_tag", "event_id"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    duplicate_mask = result.duplicated(
        ["stock_code", "effective_date", "event_type"],
        keep="first",
    )
    result.loc[duplicate_mask, "included"] = False
    result.loc[duplicate_mask, "skip_reason"] = "duplicate_same_stock_date_type"
    return result


def _open_trading_dates(connection: duckdb.DuckDBPyConnection) -> list[date]:
    rows = connection.execute(
        """
        SELECT trade_date
        FROM trading_calendar
        WHERE is_open = true
        ORDER BY trade_date
        """
    ).fetchall()
    return [_as_date(row[0]) for row in rows]


def _price_map(
    connection: duckdb.DuckDBPyConnection,
) -> dict[tuple[str, date], dict[str, object]]:
    frame = connection.execute(
        """
        SELECT stock_code, trade_date, close, adj_factor
        FROM daily_prices
        ORDER BY stock_code, trade_date
        """
    ).df()
    result: dict[tuple[str, date], dict[str, object]] = {}
    if frame.empty:
        return result
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    for row in frame.itertuples(index=False):
        result[(str(row.stock_code), row.trade_date)] = {
            "close": row.close,
            "adj_factor": row.adj_factor,
        }
    return result


def _cached_benchmark_return(
    *,
    connection: duckdb.DuckDBPyConnection,
    cache: dict[tuple[date, date, str, str | None], float],
    price_map: dict[tuple[str, date], dict[str, object]],
    event_date: date,
    future_date: date,
    index_code: str | None,
    benchmark: str,
) -> float:
    key = (event_date, future_date, benchmark, index_code)
    if key not in cache:
        cache[key] = _benchmark_return(
            connection=connection,
            price_map=price_map,
            event_date=event_date,
            future_date=future_date,
            index_code=index_code,
            benchmark=benchmark,
        )
    return cache[key]


def _benchmark_return(
    *,
    connection: duckdb.DuckDBPyConnection,
    price_map: dict[tuple[str, date], dict[str, object]],
    event_date: date,
    future_date: date,
    index_code: str | None,
    benchmark: str,
) -> float:
    if benchmark == "none":
        return float("nan")
    if index_code is None:
        return float("nan")

    universe = query_universe_members_as_of(
        connection,
        event_date,
        index_code=index_code,
    )
    if universe.empty:
        return float("nan")
    members = (
        universe.loc[:, ["stock_code"]]
        .dropna()
        .drop_duplicates("stock_code", keep="first")
        .sort_values("stock_code", kind="mergesort")
        .reset_index(drop=True)
    )
    returns: list[tuple[str, float]] = []
    for stock_code in members["stock_code"].astype(str):
        start_price = _adjusted_close(price_map.get((stock_code, event_date)))
        end_price = _adjusted_close(price_map.get((stock_code, future_date)))
        if start_price is None or end_price is None:
            continue
        returns.append((stock_code, end_price / start_price - 1.0))
    if not returns:
        return float("nan")

    returns_frame = pd.DataFrame(returns, columns=["stock_code", "stock_return"])
    if benchmark == "synthetic_equal_weight":
        return float(returns_frame["stock_return"].mean())

    valuations = _valuation_on_date(connection, event_date)
    weighted = returns_frame.merge(valuations, on="stock_code", how="left")
    weighted["market_cap"] = pd.to_numeric(weighted["float_mv"], errors="coerce")
    weighted["market_cap"] = weighted["market_cap"].where(
        weighted["market_cap"] > 0,
        pd.to_numeric(weighted["total_mv"], errors="coerce"),
    )
    weighted["market_cap"] = weighted["market_cap"].where(weighted["market_cap"] > 0)
    total_cap = weighted["market_cap"].sum(skipna=True)
    if pd.isna(total_cap) or float(total_cap) <= 0:
        return float(weighted["stock_return"].mean())
    weighted["weight"] = weighted["market_cap"].fillna(0.0) / float(total_cap)
    return float((weighted["weight"] * weighted["stock_return"]).sum())


def _valuation_on_date(
    connection: duckdb.DuckDBPyConnection,
    trade_date: date,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT stock_code, float_mv, total_mv
        FROM valuation_daily
        WHERE trade_date = ?
        ORDER BY stock_code
        """,
        [trade_date],
    ).df()
    if frame.empty:
        return pd.DataFrame(columns=["stock_code", "float_mv", "total_mv"])
    return frame


def _adjusted_close(row: dict[str, object] | None) -> float | None:
    if row is None:
        return None
    close = row.get("close")
    if pd.isna(close):
        return None
    close_value = float(close)
    if close_value <= 0:
        return None
    adj_factor = row.get("adj_factor")
    if pd.isna(adj_factor):
        return close_value
    return close_value * float(adj_factor)


def _summarize_window_returns(window_returns: pd.DataFrame) -> pd.DataFrame:
    if window_returns.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    grouped = window_returns.groupby(
        ["event_source", "event_type", "horizon"],
        dropna=False,
        sort=True,
    )
    for (event_source, event_type, horizon), group in grouped:
        excess = pd.to_numeric(group["excess_return"], errors="coerce")
        event_return = pd.to_numeric(group["event_return"], errors="coerce")
        benchmark_return = pd.to_numeric(group["benchmark_return"], errors="coerce")
        rows.append(
            {
                "event_source": event_source,
                "event_type": event_type,
                "horizon": int(horizon),
                "sample_count": int(len(group)),
                "mean_event_return": event_return.mean(),
                "median_event_return": event_return.median(),
                "win_rate": _rate(event_return),
                "mean_benchmark_return": benchmark_return.mean(),
                "mean_excess_return": excess.mean(),
                "median_excess_return": excess.median(),
                "excess_win_rate": _rate(excess),
                "p25_excess_return": excess.quantile(0.25),
                "p75_excess_return": excess.quantile(0.75),
            }
        )
    return pd.DataFrame(rows, columns=EVENT_SUMMARY_COLUMNS).sort_values(
        ["event_source", "event_type", "horizon"],
        kind="mergesort",
    ).reset_index(drop=True)


def _rate(values: pd.Series) -> float:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    if valid.empty:
        return float("nan")
    return float((valid > 0).mean())


def _skip_warnings(samples: pd.DataFrame) -> list[str]:
    skipped = samples[~samples["included"].astype(bool)]
    if skipped.empty:
        return []
    counts = skipped.groupby("skip_reason", dropna=False).size().sort_index()
    return [
        "Skipped event samples: "
        + ", ".join(f"{reason or '(empty)'}={int(count)}" for reason, count in counts.items())
    ]


def _finalize_samples(samples: pd.DataFrame) -> pd.DataFrame:
    result = samples.copy()
    for column in EVENT_SAMPLE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result = result.loc[:, EVENT_SAMPLE_COLUMNS]
    result["included"] = result["included"].astype(bool)
    result["available_max_horizon"] = pd.to_numeric(
        result["available_max_horizon"],
        errors="coerce",
    ).fillna(0).astype(int)
    return result.sort_values(
        ["effective_date", "event_type", "stock_code", "event_id"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def _finalize_window_returns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_window_returns()
    result = frame.copy()
    for column in EVENT_WINDOW_RETURN_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result.loc[:, EVENT_WINDOW_RETURN_COLUMNS].sort_values(
        ["event_date", "event_type", "stock_code", "event_id", "horizon"],
        kind="mergesort",
    ).reset_index(drop=True)


def _empty_samples() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_SAMPLE_COLUMNS)


def _empty_window_returns() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_WINDOW_RETURN_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_SUMMARY_COLUMNS)


def _normalize_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    parsed = tuple(dict.fromkeys(int(value) for value in horizons))
    if not parsed:
        raise ValueError("--horizon must include at least one positive integer.")
    invalid = [value for value in parsed if value <= 0]
    if invalid:
        raise ValueError("--horizon values must be positive integers.")
    return parsed


def _normalize_event_types(event_types: Sequence[str]) -> tuple[str, ...]:
    parsed = tuple(
        dict.fromkeys(str(value).strip() for value in event_types if str(value).strip())
    )
    if not parsed:
        raise ValueError("--event-type must be provided at least once.")
    return parsed


def _json_object(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        if pd.isna(value):
            return {}
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list_non_empty(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0


def _as_date(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Unsupported date value: {value!r}")
