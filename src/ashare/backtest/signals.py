"""Signal loading and Top N target construction for Phase 1b backtests."""

from __future__ import annotations

from collections.abc import Mapping

import duckdb
import pandas as pd

from ashare.pit.asof import DateLike, parse_as_of_date, query_universe_members_as_of
from ashare.storage.universe_snapshots import (
    load_factor_run_universe,
    require_factor_run_universe_data_source,
)


HARD_FILTER_NAMES = ("is_st", "is_suspended", "is_delisted", "low_liquidity")
TARGET_COLUMNS = [
    "signal_date",
    "stock_code",
    "target_weight",
    "sort_factor",
    "sort_factor_value",
    "rank",
]


def build_topn_targets(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int,
    data_dictionary: Mapping[str, object],
    data_source: str | None = None,
    require_universe_snapshot: bool = False,
    require_historical_pit_universe: bool = False,
) -> pd.DataFrame:
    """Build PIT Top N equal-weight targets from stored ``factor_values``."""
    parsed_signal_date = parse_as_of_date(signal_date)
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    if not sort_factor or not str(sort_factor).strip():
        raise ValueError("sort_factor must be explicitly provided.")
    if not index_code or not str(index_code).strip():
        raise ValueError("index_code must be explicitly provided.")
    if top_n <= 0:
        raise ValueError("top_n must be positive.")

    factor_metadata = _factor_metadata(data_dictionary)
    direction = _factor_direction(factor_metadata, sort_factor)
    if direction == "boolean_filter":
        raise ValueError(f"sort_factor cannot be a boolean_filter: {sort_factor}")
    if direction not in {"higher_is_better", "lower_is_better"}:
        raise ValueError(f"sort_factor must have a sortable direction: {sort_factor}")

    snapshot = load_factor_run_universe(
        connection,
        source_run_id=source_run_id,
        trade_date=parsed_signal_date,
        index_code=index_code,
    )
    if snapshot.empty:
        if require_universe_snapshot:
            raise ValueError(
                "Formal backtest requires factor_run_universe rows for source_run_id "
                f"{source_run_id} on {parsed_signal_date.isoformat()}; rerun "
                "calculate-factors with a historical PIT universe before formal use."
            )
        universe = query_universe_members_as_of(
            connection,
            parsed_signal_date,
            index_code=index_code,
            source_tag=None if data_source == "legacy" else data_source,
        )
    else:
        kinds = sorted(str(value) for value in snapshot["universe_kind"].dropna().unique())
        if require_historical_pit_universe and kinds != ["historical_pit"]:
            raise ValueError(
                "Formal backtest requires historical PIT universe snapshots; "
                f"found universe_kind={','.join(kinds) or 'unknown'} for "
                f"{source_run_id} on {parsed_signal_date.isoformat()}."
            )
        if require_historical_pit_universe:
            require_factor_run_universe_data_source(
                snapshot,
                data_source=data_source,
                context="Formal backtest",
            )
        universe = snapshot
    universe_codes = sorted(universe["stock_code"].dropna().unique().tolist())
    if not universe_codes:
        return _empty_targets()

    factor_values = load_latest_signal_factor_values(
        connection=connection,
        signal_date=parsed_signal_date,
        source_run_id=source_run_id,
        factor_names=[sort_factor, *HARD_FILTER_NAMES],
    )
    if factor_values.empty:
        return _empty_targets()

    wide = factor_values.pivot(
        index="stock_code",
        columns="factor_name",
        values="factor_value",
    ).reset_index()
    wide.columns.name = None
    wide = wide[wide["stock_code"].isin(universe_codes)].copy()
    if wide.empty:
        return _empty_targets()

    eligible = wide[_hard_filter_pass_mask(wide)].copy()
    if sort_factor not in eligible.columns:
        return _empty_targets()
    eligible = eligible[pd.notna(eligible[sort_factor])].copy()
    if eligible.empty:
        return _empty_targets()

    ascending = direction == "lower_is_better"
    selected = (
        eligible.sort_values(
            [sort_factor, "stock_code"],
            ascending=[ascending, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )
    selected_count = len(selected)
    selected.insert(0, "rank", range(1, selected_count + 1))
    selected["signal_date"] = parsed_signal_date
    selected["target_weight"] = 1.0 / selected_count if selected_count else 0.0
    selected["sort_factor"] = sort_factor
    selected["sort_factor_value"] = selected[sort_factor].astype(float)
    return selected.loc[:, TARGET_COLUMNS].reset_index(drop=True)


def has_signal_rows(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    source_run_id: str,
) -> bool:
    """Return whether any factor rows exist for a signal date and run."""
    parsed_signal_date = parse_as_of_date(signal_date)
    row = connection.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM factor_values
        WHERE source_run_id = ?
          AND trade_date = ?
          AND as_of_date <= ?
        """,
        [source_run_id, parsed_signal_date, parsed_signal_date],
    ).fetchone()
    return bool(row and row[0])


def load_latest_signal_factor_values(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    source_run_id: str,
    factor_names: list[str],
) -> pd.DataFrame:
    """Load latest visible factor rows and fail on duplicate keys at max ``as_of_date``."""
    parsed_signal_date = parse_as_of_date(signal_date)
    names = tuple(dict.fromkeys(str(name) for name in factor_names))
    if not names:
        return _empty_factor_values()

    placeholders = ", ".join("?" for _ in names)
    query = f"""
        SELECT stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        FROM factor_values
        WHERE source_run_id = ?
          AND trade_date = ?
          AND as_of_date <= ?
          AND factor_name IN ({placeholders})
        ORDER BY stock_code, factor_name, as_of_date
    """
    frame = connection.execute(
        query,
        [source_run_id, parsed_signal_date, parsed_signal_date, *names],
    ).df()
    if frame.empty:
        return _empty_factor_values()

    frame = frame.loc[
        :,
        ["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date", "source_run_id"],
    ].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    frame["factor_value"] = pd.to_numeric(frame["factor_value"], errors="coerce")

    key_columns = ["source_run_id", "stock_code", "trade_date", "factor_name"]
    max_as_of = frame.groupby(key_columns, dropna=False)["as_of_date"].transform("max")
    latest = frame[frame["as_of_date"].eq(max_as_of)].copy()
    _fail_on_duplicate_latest_keys(latest)
    return latest.reset_index(drop=True)


def _fail_on_duplicate_latest_keys(factor_values: pd.DataFrame) -> None:
    duplicate_counts = (
        factor_values.groupby(
            ["source_run_id", "stock_code", "trade_date", "as_of_date", "factor_name"],
            dropna=False,
        )
        .size()
        .reset_index(name="row_count")
    )
    duplicates = duplicate_counts[duplicate_counts["row_count"] >= 2]
    if duplicates.empty:
        return

    samples = []
    for row in duplicates.head(5).itertuples(index=False):
        samples.append(
            f"({row.source_run_id}, {row.stock_code}, {row.trade_date}, "
            f"{row.as_of_date}, {row.factor_name}, count={row.row_count})"
        )
    raise ValueError(
        "Duplicate factor_values rows for latest visible "
        "(source_run_id, stock_code, trade_date, as_of_date, factor_name). "
        f"Examples: {'; '.join(samples)}"
    )


def _hard_filter_pass_mask(wide: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=wide.index)
    for hard_filter in HARD_FILTER_NAMES:
        if hard_filter not in wide.columns:
            mask &= False
            continue
        mask &= wide[hard_filter].notna() & wide[hard_filter].eq(0.0)
    return mask


def _factor_metadata(data_dictionary: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    factors = data_dictionary.get("factors")
    if not isinstance(factors, Mapping):
        raise ValueError("data_dictionary.factors must be a mapping.")
    result: dict[str, Mapping[str, object]] = {}
    for name, value in factors.items():
        if isinstance(value, Mapping):
            result[str(name)] = value
    return result


def _factor_direction(factor_metadata: Mapping[str, Mapping[str, object]], factor_name: str) -> str:
    entry = factor_metadata.get(factor_name)
    if entry is None:
        raise ValueError(f"Unknown factor name: {factor_name}")
    direction = entry.get("direction")
    if not isinstance(direction, str):
        raise ValueError(f"Missing direction for factor: {factor_name}")
    return direction


def _empty_targets() -> pd.DataFrame:
    return pd.DataFrame(columns=TARGET_COLUMNS)


def _empty_factor_values() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "stock_code",
            "trade_date",
            "factor_name",
            "factor_value",
            "as_of_date",
            "source_run_id",
        ]
    )
