"""Phase 1a-7 real data ingest pilot orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from ashare.ingest.cache import CacheKey, build_params_hash, read_cached_frame, write_cached_frame
from ashare.ingest.contracts import (
    DATASET_COLUMNS,
    FieldValidationIssue,
    exchange_from_stock_code,
    normalize_dataset,
    validate_dataset,
)
from ashare.ingest.providers import MarketDataProvider, ProviderError
from ashare.ingest.quality import build_data_quality_report, write_data_quality_report
from ashare.pit.asof import parse_as_of_date
from ashare.pit.effective_date import calculate_effective_date
from ashare.storage.db import connect, init_db


DateLike = str | date | datetime | pd.Timestamp
TARGET_DATASETS = (
    "trading_calendar",
    "securities",
    "universe_members",
    "daily_prices",
    "valuation_daily",
)
CACHE_MODES = {"use", "refresh", "offline"}


@dataclass(frozen=True)
class RealPilotIngestResult:
    """Result returned by the real pilot ingest path."""

    source: str
    effective_source: str
    source_tag: str
    db_path: Path
    row_counts: dict[str, int]
    cache_counts: dict[str, int]
    quality_report_paths: dict[str, Path]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _PreparedData:
    frames: dict[str, pd.DataFrame]
    issues: tuple[FieldValidationIssue, ...]
    cache_events: tuple[dict[str, object], ...]
    sample_stock_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    universe_members_mode: str


def ingest_real_pilot(
    db_path: str | Path,
    provider: MarketDataProvider,
    universe: str,
    index_code: str,
    start_date: DateLike,
    end_date: DateLike,
    universe_as_of_date: DateLike,
    cache_dir: str | Path,
    cache_mode: str = "use",
    fallback_provider: MarketDataProvider | None = None,
    allow_fallback: bool = False,
    max_symbols: int | None = None,
    quality_report_dir: str | Path | None = None,
    source_tag: str | None = None,
    overwrite_report: bool = False,
    extra_warnings: Sequence[str] | None = None,
    requested_source: str | None = None,
) -> RealPilotIngestResult:
    """Run the bounded real data ingest pilot and write quality reports."""
    start = parse_as_of_date(start_date)
    end = parse_as_of_date(end_date)
    universe_as_of = parse_as_of_date(universe_as_of_date)
    if start > end:
        raise ValueError("--from must be on or before --to.")
    if universe != "hs300":
        raise ValueError("Phase 1a-7 only supports --universe hs300.")
    if cache_mode not in CACHE_MODES:
        raise ValueError(f"Unsupported cache_mode: {cache_mode}")
    if max_symbols is not None and max_symbols <= 0:
        raise ValueError("--max-symbols must be positive when provided.")

    base_warnings = list(extra_warnings or ())
    if universe_as_of > start:
        base_warnings.append(
            "universe_as_of_date is after start_date; PIT universe may be empty before "
            f"{universe_as_of.isoformat()}."
        )

    try:
        return _run_provider(
            db_path=Path(db_path),
            provider=provider,
            source=requested_source or provider.name,
            effective_source=provider.name,
            source_tag=source_tag or provider.name,
            universe=universe,
            index_code=index_code,
            start_date=start,
            end_date=end,
            universe_as_of_date=universe_as_of,
            cache_dir=cache_dir,
            cache_mode=cache_mode,
            max_symbols=max_symbols,
            quality_report_dir=quality_report_dir,
            overwrite_report=overwrite_report,
            warnings=tuple(base_warnings),
        )
    except Exception as exc:
        if provider.name == "csv" or not allow_fallback or fallback_provider is None:
            raise
        fallback_warning = (
            f"Primary provider {provider.name} failed; using explicit CSV fallback: {exc}"
        )
        return _run_provider(
            db_path=Path(db_path),
            provider=fallback_provider,
            source=requested_source or provider.name,
            effective_source="csv_fallback",
            source_tag=source_tag or "csv_fallback",
            universe=universe,
            index_code=index_code,
            start_date=start,
            end_date=end,
            universe_as_of_date=universe_as_of,
            cache_dir=cache_dir,
            cache_mode=cache_mode,
            max_symbols=max_symbols,
            quality_report_dir=quality_report_dir,
            overwrite_report=overwrite_report,
            warnings=tuple([*base_warnings, fallback_warning]),
        )


def _run_provider(
    *,
    db_path: Path,
    provider: MarketDataProvider,
    source: str,
    effective_source: str,
    source_tag: str,
    universe: str,
    index_code: str,
    start_date: date,
    end_date: date,
    universe_as_of_date: date,
    cache_dir: str | Path,
    cache_mode: str,
    max_symbols: int | None,
    quality_report_dir: str | Path | None,
    overwrite_report: bool,
    warnings: tuple[str, ...],
) -> RealPilotIngestResult:
    prepared = _prepare_provider_data(
        provider=provider,
        effective_source=effective_source,
        source_tag=source_tag,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        universe_as_of_date=universe_as_of_date,
        cache_dir=cache_dir,
        cache_mode=cache_mode,
        max_symbols=max_symbols,
        warnings=warnings,
    )

    init_db(db_path)
    row_counts = _write_frames(
        db_path=db_path,
        source_tag=source_tag,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        frames=prepared.frames,
    )
    report_dir = (
        Path(quality_report_dir)
        if quality_report_dir is not None
        else Path("data/reports/generated/phase1a7/data-quality")
    )
    report = build_data_quality_report(
        source=source,
        effective_source=effective_source,
        source_tag=source_tag,
        universe=universe,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        universe_as_of_date=universe_as_of_date,
        frames=prepared.frames,
        issues=prepared.issues,
        cache_events=prepared.cache_events,
        warnings=prepared.warnings,
        sample_stock_codes=prepared.sample_stock_codes,
        universe_members_mode=prepared.universe_members_mode,
    )
    paths = write_data_quality_report(report, report_dir, overwrite=overwrite_report)

    return RealPilotIngestResult(
        source=source,
        effective_source=effective_source,
        source_tag=source_tag,
        db_path=db_path,
        row_counts=row_counts,
        cache_counts=_cache_counts(prepared.cache_events),
        quality_report_paths=paths,
        warnings=report.warnings,
    )


def _prepare_provider_data(
    *,
    provider: MarketDataProvider,
    effective_source: str,
    source_tag: str,
    index_code: str,
    start_date: date,
    end_date: date,
    universe_as_of_date: date,
    cache_dir: str | Path,
    cache_mode: str,
    max_symbols: int | None,
    warnings: tuple[str, ...],
) -> _PreparedData:
    cache_events: list[dict[str, object]] = []
    runtime_warnings = list(warnings)
    capability_check = getattr(provider, "capability_check", None)
    if callable(capability_check):
        check = capability_check()
        runtime_warnings.append(check.as_warning())
        if getattr(check, "status", "PASS") != "PASS":
            raise ProviderError(check.as_warning())

    trading_raw = _cached_fetch(
        provider,
        "trading_calendar",
        {"start_date": start_date, "end_date": end_date},
        cache_dir,
        cache_mode,
        lambda: provider.fetch_trading_calendar(start_date, end_date),
        cache_events,
    )
    members_raw = _cached_fetch(
        provider,
        "universe_members",
        {"index_code": index_code, "as_of_date": universe_as_of_date},
        cache_dir,
        cache_mode,
        lambda: provider.fetch_index_members(index_code, universe_as_of_date),
        cache_events,
    )
    normalized_members_for_codes = normalize_dataset("universe_members", members_raw)
    member_security_names = _extract_member_security_names(members_raw)
    if "index_code" not in normalized_members_for_codes:
        normalized_members_for_codes["index_code"] = index_code
    normalized_members_for_codes["index_code"] = normalized_members_for_codes[
        "index_code"
    ].fillna(index_code)
    stock_codes = sorted(
        code
        for code in normalized_members_for_codes["stock_code"].dropna().unique().tolist()
        if code
    )
    if max_symbols is not None:
        stock_codes = stock_codes[:max_symbols]
        runtime_warnings.append(
            "--max-symbols applied; sampled stock_code list: " + ", ".join(stock_codes)
        )
    if not stock_codes:
        raise ProviderError("Provider returned no valid stock codes for the requested universe.")

    securities_raw = _cached_fetch(
        provider,
        "securities",
        {"stock_codes": stock_codes, "as_of_date": universe_as_of_date},
        cache_dir,
        cache_mode,
        lambda: provider.fetch_securities(stock_codes, universe_as_of_date),
        cache_events,
    )
    prices_raw = _cached_fetch(
        provider,
        "daily_prices",
        {"stock_codes": stock_codes, "start_date": start_date, "end_date": end_date},
        cache_dir,
        cache_mode,
        lambda: provider.fetch_daily_prices(stock_codes, start_date, end_date),
        cache_events,
    )
    valuation_raw = _cached_fetch(
        provider,
        "valuation_daily",
        {"stock_codes": stock_codes, "start_date": start_date, "end_date": end_date},
        cache_dir,
        cache_mode,
        lambda: provider.fetch_valuation_daily(stock_codes, start_date, end_date),
        cache_events,
    )

    frames: dict[str, pd.DataFrame] = {}
    issues: list[FieldValidationIssue] = []
    sample_stock_codes = tuple(stock_codes)

    trading = normalize_dataset("trading_calendar", trading_raw)
    trading = _filter_date_range(trading, "trade_date", start_date, end_date)
    trading["source"] = source_tag
    frames["trading_calendar"], validation_issues = validate_dataset("trading_calendar", trading)
    issues.extend(validation_issues)

    members = normalize_dataset("universe_members", members_raw)
    members = _prepare_members(
        members,
        index_code=index_code,
        source_tag=source_tag,
        universe_as_of_date=universe_as_of_date,
        stock_codes=sample_stock_codes,
        trading_calendar=frames["trading_calendar"],
    )
    universe_members_mode = _universe_members_mode(members, universe_as_of_date)
    frames["universe_members"], validation_issues = validate_dataset("universe_members", members)
    issues.extend(validation_issues)

    securities = normalize_dataset("securities", securities_raw)
    securities, securities_warnings = _prepare_securities(
        securities,
        members=frames["universe_members"],
        source_tag=source_tag,
        member_security_names=member_security_names,
        universe_as_of_date=universe_as_of_date,
        stock_codes=sample_stock_codes,
        trading_calendar=frames["trading_calendar"],
    )
    runtime_warnings.extend(securities_warnings)
    frames["securities"], validation_issues = validate_dataset("securities", securities)
    issues.extend(validation_issues)

    daily_prices = normalize_dataset("daily_prices", prices_raw)
    daily_prices = _filter_stock_and_dates(daily_prices, sample_stock_codes, start_date, end_date)
    daily_prices["source"] = source_tag
    frames["daily_prices"], validation_issues = validate_dataset("daily_prices", daily_prices)
    issues.extend(validation_issues)

    valuation = normalize_dataset("valuation_daily", valuation_raw)
    valuation = _filter_stock_and_dates(valuation, sample_stock_codes, start_date, end_date)
    valuation["source"] = source_tag
    frames["valuation_daily"], validation_issues = validate_dataset("valuation_daily", valuation)
    issues.extend(validation_issues)

    _ensure_non_empty(frames)
    _write_normalized_caches(
        provider=provider,
        effective_source=effective_source,
        source_tag=source_tag,
        frames=frames,
        cache_dir=cache_dir,
        cache_mode=cache_mode,
        request_params={
            "index_code": index_code,
            "start_date": start_date,
            "end_date": end_date,
            "universe_as_of_date": universe_as_of_date,
            "stock_codes": sample_stock_codes,
        },
    )
    return _PreparedData(
        frames=frames,
        issues=tuple(issues),
        cache_events=tuple(cache_events),
        sample_stock_codes=sample_stock_codes,
        warnings=tuple(runtime_warnings),
        universe_members_mode=universe_members_mode,
    )


def _cached_fetch(
    provider: MarketDataProvider,
    dataset: str,
    params: Mapping[str, object],
    cache_dir: str | Path,
    cache_mode: str,
    fetch: Callable[[], pd.DataFrame],
    cache_events: list[dict[str, object]],
) -> pd.DataFrame:
    params_hash = build_params_hash(provider.name, dataset, params)
    key = CacheKey(provider.name, dataset, params_hash)
    if cache_mode != "refresh":
        cached = read_cached_frame(cache_dir, key)
        if cached is not None:
            cache_events.append(_cache_event(dataset, cache_mode, "hit", key, None))
            return cached
    if cache_mode == "offline" and provider.name != "csv":
        cache_events.append(_cache_event(dataset, cache_mode, "miss", key, None))
        raise ProviderError(f"Cache miss for {dataset} in offline mode.")

    frame = fetch()
    path = write_cached_frame(
        cache_dir,
        key,
        frame,
        {
            "source": provider.name,
            "dataset": dataset,
            "request_params": params,
            "params_hash": params_hash,
            "row_count": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "provider_version_or_unknown": provider.provider_version_or_unknown,
        },
    )
    cache_events.append(_cache_event(dataset, cache_mode, "miss", key, path))
    return frame


def _cache_event(
    dataset: str,
    cache_mode: str,
    status: str,
    key: CacheKey,
    path: Path | None,
) -> dict[str, object]:
    return {
        "dataset": dataset,
        "cache_mode": cache_mode,
        "status": status,
        "source": key.source,
        "params_hash": key.params_hash,
        "path": str(path) if path is not None else "",
    }


def _cache_counts(cache_events: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = {"hit": 0, "miss": 0}
    for event in cache_events:
        status = str(event.get("status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def _write_normalized_caches(
    *,
    provider: MarketDataProvider,
    effective_source: str,
    source_tag: str,
    frames: Mapping[str, pd.DataFrame],
    cache_dir: str | Path,
    cache_mode: str,
    request_params: Mapping[str, object],
) -> None:
    if cache_mode == "offline":
        return
    for dataset, frame in frames.items():
        normalized_dataset = f"{dataset}_normalized"
        params = dict(request_params)
        params["source_tag"] = source_tag
        params_hash = build_params_hash(effective_source, normalized_dataset, params)
        key = CacheKey(effective_source, normalized_dataset, params_hash)
        write_cached_frame(
            cache_dir,
            key,
            frame,
            {
                "source": effective_source,
                "dataset": normalized_dataset,
                "request_params": params,
                "params_hash": params_hash,
                "row_count": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
                "provider_version_or_unknown": provider.provider_version_or_unknown,
            },
        )


def _extract_member_security_names(members_raw: pd.DataFrame) -> pd.Series | None:
    try:
        securities_like = normalize_dataset("securities", members_raw)
    except (TypeError, ValueError):
        return None
    if securities_like.empty or "stock_code" not in securities_like or "stock_name" not in securities_like:
        return None
    names = securities_like.dropna(subset=["stock_code"]).set_index("stock_code")["stock_name"]
    return names.dropna()


def _prepare_members(
    frame: pd.DataFrame,
    *,
    index_code: str,
    source_tag: str,
    universe_as_of_date: date,
    stock_codes: Sequence[str],
    trading_calendar: pd.DataFrame,
) -> pd.DataFrame:
    result = frame.copy()
    result["index_code"] = result.get("index_code", pd.Series(index_code, index=result.index)).fillna(
        index_code
    )
    if "in_date" not in result:
        result["in_date"] = universe_as_of_date
    result["in_date"] = result["in_date"].fillna(universe_as_of_date)
    for column in ["out_date", "in_publish_time", "out_publish_time", "out_effective_date"]:
        if column not in result:
            result[column] = pd.NA
    if "in_effective_date" not in result:
        result["in_effective_date"] = pd.NA
    result["in_effective_date"] = _fill_effective_column(
        result,
        effective_column="in_effective_date",
        publish_column="in_publish_time",
        fallback_column="in_date",
        trading_calendar=trading_calendar,
    )
    result["out_effective_date"] = _fill_effective_column(
        result,
        effective_column="out_effective_date",
        publish_column="out_publish_time",
        fallback_column="out_date",
        trading_calendar=trading_calendar,
    )
    result["source"] = source_tag
    result["source_tag"] = source_tag
    result["universe_kind"] = _universe_members_mode(result, universe_as_of_date)
    result = result.loc[result["stock_code"].isin(stock_codes)]
    result = result.loc[result["index_code"] == index_code]
    return result.reset_index(drop=True)


def _prepare_securities(
    frame: pd.DataFrame,
    *,
    members: pd.DataFrame,
    source_tag: str,
    member_security_names: pd.Series | None,
    universe_as_of_date: date,
    stock_codes: Sequence[str],
    trading_calendar: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    warnings: list[str] = []
    result = frame.copy()
    if result.empty:
        result = pd.DataFrame({"stock_code": list(stock_codes)})
    result = result.loc[result["stock_code"].isin(stock_codes)].copy()
    missing_codes = sorted(set(stock_codes) - set(result["stock_code"].dropna().tolist()))
    if missing_codes:
        result = pd.concat([result, pd.DataFrame({"stock_code": missing_codes})], ignore_index=True)

    if "stock_name" not in result:
        result["stock_name"] = pd.NA
    if "stock_name" in members.columns:
        names = members.dropna(subset=["stock_code"]).set_index("stock_code").get("stock_name")
        if names is not None:
            missing_name = result["stock_name"].isna() | (
                result["stock_name"].astype("string").str.strip() == ""
            )
            result.loc[missing_name, "stock_name"] = result.loc[missing_name, "stock_code"].map(names)
    if member_security_names is not None:
        missing_name = result["stock_name"].isna() | (
            result["stock_name"].astype("string").str.strip() == ""
        )
        result.loc[missing_name, "stock_name"] = result.loc[missing_name, "stock_code"].map(
            member_security_names
        )

    if "exchange" not in result:
        result["exchange"] = pd.NA
    missing_exchange = result["exchange"].isna() | (
        result["exchange"].astype("string").str.strip() == ""
    )
    result.loc[missing_exchange, "exchange"] = result.loc[missing_exchange, "stock_code"].map(
        exchange_from_stock_code
    )

    if "list_date" not in result:
        result["list_date"] = pd.NA
    missing_list_date = result["list_date"].isna() | (
        result["list_date"].astype("string").str.strip() == ""
    )
    if bool(missing_list_date.any()):
        result.loc[missing_list_date, "list_date"] = universe_as_of_date
        warnings.append(
            "securities.list_date used synthetic universe_as_of_date for "
            f"{int(missing_list_date.sum())} stock(s)."
        )
    for column in ["delist_date", "delist_publish_time", "delist_effective_date"]:
        if column not in result:
            result[column] = pd.NA
    result["delist_effective_date"] = _fill_effective_column(
        result,
        effective_column="delist_effective_date",
        publish_column="delist_publish_time",
        fallback_column="delist_date",
        trading_calendar=trading_calendar,
    )
    result["source"] = source_tag
    return result.loc[:, DATASET_COLUMNS["securities"]].reset_index(drop=True), tuple(warnings)


def _fill_effective_column(
    frame: pd.DataFrame,
    *,
    effective_column: str,
    publish_column: str,
    fallback_column: str,
    trading_calendar: pd.DataFrame,
) -> pd.Series:
    result = frame[effective_column].copy()
    missing = result.isna() | (result.astype("string").str.strip() == "")
    has_publish = publish_column in frame.columns and frame[publish_column].notna() & (
        frame[publish_column].astype("string").str.strip() != ""
    )
    publish_mask = missing & has_publish
    if bool(publish_mask.any()):
        trading_days = sorted(
            trading_calendar.loc[trading_calendar["is_open"].fillna(False), "trade_date"].tolist()
        )
        result.loc[publish_mask] = frame.loc[publish_mask, publish_column].map(
            lambda value: calculate_effective_date(pd.to_datetime(value).to_pydatetime(), trading_days)
        )
    fallback_mask = missing & ~publish_mask
    if fallback_column in frame.columns:
        result.loc[fallback_mask] = frame.loc[fallback_mask, fallback_column]
    return result


def _filter_stock_and_dates(
    frame: pd.DataFrame,
    stock_codes: Sequence[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    filtered = frame.loc[frame["stock_code"].isin(stock_codes)].copy()
    return _filter_date_range(filtered, "trade_date", start_date, end_date)


def _filter_date_range(
    frame: pd.DataFrame,
    column: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    return frame.loc[(frame[column] >= start_date) & (frame[column] <= end_date)].reset_index(
        drop=True
    )


def _universe_members_mode(frame: pd.DataFrame, universe_as_of_date: date) -> str:
    if frame.empty:
        return "empty"
    if frame["in_date"].nunique() == 1 and frame["in_date"].iloc[0] == universe_as_of_date:
        return "current_snapshot"
    return "historical_pit"


def _ensure_non_empty(frames: Mapping[str, pd.DataFrame]) -> None:
    empty = [dataset for dataset in TARGET_DATASETS if frames[dataset].empty]
    if empty:
        raise ProviderError("Provider returned empty normalized dataset(s): " + ", ".join(empty))


def _write_frames(
    *,
    db_path: Path,
    source_tag: str,
    index_code: str,
    start_date: date,
    end_date: date,
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, int]:
    connection = connect(db_path)
    try:
        connection.execute("BEGIN TRANSACTION")
        try:
            _replace_trading_calendar(connection, frames["trading_calendar"], source_tag, start_date, end_date)
            _replace_securities(connection, frames["securities"], source_tag)
            _replace_universe_members(connection, frames["universe_members"], source_tag, index_code)
            _replace_daily_prices(connection, frames["daily_prices"], source_tag, start_date, end_date)
            _replace_valuation_daily(connection, frames["valuation_daily"], source_tag, start_date, end_date)
            row_counts = _readback_counts(
                connection,
                source_tag=source_tag,
                index_code=index_code,
                start_date=start_date,
                end_date=end_date,
                frames=frames,
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return row_counts


def _replace_trading_calendar(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    source_tag: str,
    start_date: date,
    end_date: date,
) -> None:
    connection.execute(
        """
        DELETE FROM trading_calendar
        WHERE source = ?
          AND trade_date BETWEEN ? AND ?
        """,
        [source_tag, start_date, end_date],
    )
    _insert_frame(connection, "trading_calendar", frame)


def _replace_securities(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    source_tag: str,
) -> None:
    codes = frame[["stock_code"]].drop_duplicates()
    connection.register("_phase1a7_codes", codes)
    try:
        connection.execute(
            """
            DELETE FROM securities
            WHERE source = ?
              AND stock_code IN (SELECT stock_code FROM _phase1a7_codes)
            """,
            [source_tag],
        )
    finally:
        connection.unregister("_phase1a7_codes")
    _insert_frame(connection, "securities", frame)


def _replace_universe_members(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    source_tag: str,
    index_code: str,
) -> None:
    codes = frame[["stock_code"]].drop_duplicates()
    connection.register("_phase1a7_codes", codes)
    try:
        connection.execute(
            """
            DELETE FROM universe_members
            WHERE source_tag = ?
              AND index_code = ?
              AND stock_code IN (SELECT stock_code FROM _phase1a7_codes)
            """,
            [source_tag, index_code],
        )
    finally:
        connection.unregister("_phase1a7_codes")
    _insert_frame(connection, "universe_members", frame)


def _replace_daily_prices(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    source_tag: str,
    start_date: date,
    end_date: date,
) -> None:
    codes = frame[["stock_code"]].drop_duplicates()
    connection.register("_phase1a7_codes", codes)
    try:
        connection.execute(
            """
            DELETE FROM daily_prices
            WHERE source = ?
              AND trade_date BETWEEN ? AND ?
              AND stock_code IN (SELECT stock_code FROM _phase1a7_codes)
            """,
            [source_tag, start_date, end_date],
        )
    finally:
        connection.unregister("_phase1a7_codes")
    _insert_frame(connection, "daily_prices", frame)


def _replace_valuation_daily(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    source_tag: str,
    start_date: date,
    end_date: date,
) -> None:
    codes = frame[["stock_code"]].drop_duplicates()
    connection.register("_phase1a7_codes", codes)
    try:
        connection.execute(
            """
            DELETE FROM valuation_daily
            WHERE source = ?
              AND trade_date BETWEEN ? AND ?
              AND stock_code IN (SELECT stock_code FROM _phase1a7_codes)
            """,
            [source_tag, start_date, end_date],
        )
    finally:
        connection.unregister("_phase1a7_codes")
    _insert_frame(connection, "valuation_daily", frame)


def _insert_frame(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    frame: pd.DataFrame,
) -> None:
    if frame.empty:
        return
    columns = DATASET_COLUMNS[table]
    connection.register("_phase1a7_insert", frame.loc[:, columns])
    try:
        column_sql = ", ".join(columns)
        connection.execute(
            f"INSERT INTO {table} ({column_sql}) SELECT {column_sql} FROM _phase1a7_insert"
        )
    finally:
        connection.unregister("_phase1a7_insert")


def _readback_counts(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_tag: str,
    index_code: str,
    start_date: date,
    end_date: date,
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, int]:
    codes = frames["securities"][["stock_code"]].drop_duplicates()
    connection.register("_phase1a7_expected_codes", codes)
    try:
        counts = {
            "trading_calendar": connection.execute(
                """
                SELECT COUNT(*)
                FROM trading_calendar
                WHERE source = ?
                  AND trade_date BETWEEN ? AND ?
                """,
                [source_tag, start_date, end_date],
            ).fetchone()[0],
            "securities": connection.execute(
                """
                SELECT COUNT(*)
                FROM securities
                WHERE source = ?
                  AND stock_code IN (SELECT stock_code FROM _phase1a7_expected_codes)
                """
                ,
                [source_tag],
            ).fetchone()[0],
            "universe_members": connection.execute(
                """
                SELECT COUNT(*)
                FROM universe_members
                WHERE source_tag = ?
                  AND index_code = ?
                  AND stock_code IN (SELECT stock_code FROM _phase1a7_expected_codes)
                """,
                [source_tag, index_code],
            ).fetchone()[0],
            "daily_prices": connection.execute(
                """
                SELECT COUNT(*)
                FROM daily_prices
                WHERE source = ?
                  AND trade_date BETWEEN ? AND ?
                  AND stock_code IN (SELECT stock_code FROM _phase1a7_expected_codes)
                """,
                [source_tag, start_date, end_date],
            ).fetchone()[0],
            "valuation_daily": connection.execute(
                """
                SELECT COUNT(*)
                FROM valuation_daily
                WHERE source = ?
                  AND trade_date BETWEEN ? AND ?
                  AND stock_code IN (SELECT stock_code FROM _phase1a7_expected_codes)
                """,
                [source_tag, start_date, end_date],
            ).fetchone()[0],
        }
    finally:
        connection.unregister("_phase1a7_expected_codes")
    expected = {dataset: len(frame) for dataset, frame in frames.items()}
    mismatches = [
        f"{dataset}: expected {expected[dataset]}, read back {counts[dataset]}"
        for dataset in TARGET_DATASETS
        if counts[dataset] != expected[dataset]
    ]
    if mismatches:
        raise ValueError("Read-back row count mismatch: " + "; ".join(mismatches))
    return {dataset: int(counts[dataset]) for dataset in TARGET_DATASETS}
