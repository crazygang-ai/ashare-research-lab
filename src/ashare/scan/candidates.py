"""Minimal Phase 1a-6 candidate scan from stored factor_values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from ashare.pit.asof import (
    DateLike,
    parse_as_of_date,
    query_industry_classifications_as_of,
    query_securities_as_of,
)
from ashare.validation.runner import load_data_dictionary


HARD_FILTER_NAMES = ("is_st", "is_suspended", "is_delisted", "low_liquidity")
NO_RISK_TEXT = "未触发本阶段规则风险提示"


@dataclass(frozen=True)
class CandidateScanResult:
    candidates: pd.DataFrame
    warnings: tuple[str, ...] = ()


def scan_candidates(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    factor_names: Sequence[str] | None = None,
    top_n: int = 20,
    data_dictionary: Mapping[str, object] | None = None,
) -> CandidateScanResult:
    """Build a deterministic Top N research candidate list from one factor_values date."""
    parsed_as_of = parse_as_of_date(as_of_date)
    if not source_run_id or not str(source_run_id).strip():
        raise ValueError("source_run_id must be explicitly provided.")
    if not sort_factor or not str(sort_factor).strip():
        raise ValueError("sort_factor must be explicitly provided.")
    if top_n < 0:
        raise ValueError("top_n must be non-negative.")

    dictionary = data_dictionary if data_dictionary is not None else load_data_dictionary()
    factor_metadata = _factor_metadata(dictionary)
    sort_factor = str(sort_factor)
    _validate_factor_name(sort_factor, factor_metadata, option_name="sort_factor")
    sort_direction = _factor_direction(factor_metadata, sort_factor)
    if sort_direction not in {"higher_is_better", "lower_is_better"}:
        raise ValueError(f"sort_factor must have a sortable direction: {sort_factor}")
    display_factors = _display_factor_names(
        sort_factor=sort_factor,
        requested=factor_names,
        factor_metadata=factor_metadata,
    )

    factor_values = _load_scan_factor_values(connection, parsed_as_of, source_run_id)
    if factor_values.empty:
        raise ValueError(
            "No scanable factor_values input found for the requested "
            "source_run_id and as_of_date with trade_date = as_of_date."
        )
    _fail_on_duplicate_factor_keys(factor_values)

    wide = _to_wide_factor_values(factor_values)
    hard_filter_mask = _hard_filter_pass_mask(wide)
    sort_factor_mask = (
        pd.notna(wide[sort_factor]) if sort_factor in wide.columns else pd.Series(False, index=wide.index)
    )
    eligible = wide[hard_filter_mask & sort_factor_mask].copy()
    if eligible.empty:
        return CandidateScanResult(
            candidates=_empty_candidates(parsed_as_of, source_run_id, sort_factor, display_factors),
            warnings=(
                "No candidates remained after hard filters and sort-factor availability checks.",
            ),
        )

    ascending = sort_direction == "lower_is_better"
    selected = (
        eligible.sort_values(
            [sort_factor, "stock_code"],
            ascending=[ascending, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )
    selected.insert(0, "rank", range(1, len(selected) + 1))
    enriched = _enrich_stock_metadata(connection, parsed_as_of, selected)
    candidates = _build_candidates_frame(
        selected=enriched,
        as_of_date=parsed_as_of,
        source_run_id=source_run_id,
        sort_factor=sort_factor,
        sort_direction=sort_direction,
        display_factors=display_factors,
        top_n=top_n,
    )
    return CandidateScanResult(candidates=candidates)


def candidate_columns(factor_names: Sequence[str]) -> list[str]:
    return [
        "rank",
        "stock_code",
        "stock_name",
        "industry_l1",
        "industry_l2",
        "as_of_date",
        "source_run_id",
        "sort_factor",
        "sort_factor_value",
        *[f"factor__{name}" for name in factor_names],
        *[f"hard_filter__{name}" for name in HARD_FILTER_NAMES],
        "selection_reason",
        "risk_tips",
    ]


def _load_scan_factor_values(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: date,
    source_run_id: str,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT stock_code, trade_date, factor_name, factor_value, as_of_date, source_run_id
        FROM factor_values
        WHERE source_run_id = ?
          AND trade_date = ?
          AND as_of_date = ?
          AND as_of_date = trade_date
        ORDER BY stock_code, factor_name
        """,
        [source_run_id, as_of_date, as_of_date],
    ).df()
    if frame.empty:
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
    result = frame.loc[
        :,
        ["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date", "source_run_id"],
    ].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    result["as_of_date"] = pd.to_datetime(result["as_of_date"]).dt.date
    result["factor_value"] = pd.to_numeric(result["factor_value"], errors="coerce")
    return result


def _fail_on_duplicate_factor_keys(factor_values: pd.DataFrame) -> None:
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
        "Duplicate factor_values rows for "
        "(source_run_id, stock_code, trade_date, as_of_date, factor_name). "
        f"Examples: {'; '.join(samples)}"
    )


def _to_wide_factor_values(factor_values: pd.DataFrame) -> pd.DataFrame:
    wide = factor_values.pivot(
        index="stock_code",
        columns="factor_name",
        values="factor_value",
    ).reset_index()
    wide.columns.name = None
    return wide.sort_values("stock_code", kind="mergesort").reset_index(drop=True)


def _hard_filter_pass_mask(wide: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=wide.index)
    for hard_filter in HARD_FILTER_NAMES:
        if hard_filter not in wide.columns:
            mask &= False
            continue
        mask &= wide[hard_filter].notna() & wide[hard_filter].eq(0.0)
    return mask


def _enrich_stock_metadata(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: date,
    selected: pd.DataFrame,
) -> pd.DataFrame:
    result = selected.copy()
    securities = query_securities_as_of(
        connection,
        as_of_date,
        include_delisted=True,
    )
    if not securities.empty:
        securities = securities.loc[:, ["stock_code", "stock_name"]].drop_duplicates(
            "stock_code",
            keep="first",
        )
        result = result.merge(securities, on="stock_code", how="left")
    else:
        result["stock_name"] = pd.NA

    industries = query_industry_classifications_as_of(connection, as_of_date)
    if not industries.empty:
        industries = industries.loc[:, ["stock_code", "industry_l1", "industry_l2"]]
        industries = industries.drop_duplicates("stock_code", keep="first")
        result = result.merge(industries, on="stock_code", how="left")
    else:
        result["industry_l1"] = pd.NA
        result["industry_l2"] = pd.NA
    return result


def _build_candidates_frame(
    selected: pd.DataFrame,
    as_of_date: date,
    source_run_id: str,
    sort_factor: str,
    sort_direction: str,
    display_factors: Sequence[str],
    top_n: int,
) -> pd.DataFrame:
    columns = candidate_columns(display_factors)
    rows: list[dict[str, object]] = []
    for _, row in selected.iterrows():
        row_values = row.to_dict()
        output: dict[str, object] = {
            "rank": int(row_values["rank"]),
            "stock_code": row_values["stock_code"],
            "stock_name": row_values.get("stock_name", pd.NA),
            "industry_l1": row_values.get("industry_l1", pd.NA),
            "industry_l2": row_values.get("industry_l2", pd.NA),
            "as_of_date": as_of_date,
            "source_run_id": source_run_id,
            "sort_factor": sort_factor,
            "sort_factor_value": row_values[sort_factor],
        }
        for factor_name in display_factors:
            output[f"factor__{factor_name}"] = row_values.get(factor_name, pd.NA)
        for hard_filter in HARD_FILTER_NAMES:
            output[f"hard_filter__{hard_filter}"] = row_values.get(hard_filter, pd.NA)
        output["selection_reason"] = _selection_reason(
            sort_factor=sort_factor,
            sort_direction=sort_direction,
            sort_value=row_values[sort_factor],
            top_n=top_n,
        )
        output["risk_tips"] = _risk_tips(row_values, display_factors)
        rows.append(output)

    candidates = pd.DataFrame(rows, columns=columns)
    if not candidates.empty:
        candidates = candidates.sort_values("rank", kind="mergesort").reset_index(drop=True)
    return candidates


def _empty_candidates(
    as_of_date: date,
    source_run_id: str,
    sort_factor: str,
    display_factors: Sequence[str],
) -> pd.DataFrame:
    _ = (as_of_date, source_run_id, sort_factor)
    return pd.DataFrame(columns=candidate_columns(display_factors))


def _selection_reason(
    sort_factor: str,
    sort_direction: str,
    sort_value: object,
    top_n: int,
) -> str:
    return (
        f"按 {sort_factor} {sort_direction} 排序进入 Top {top_n}；"
        f"{sort_factor}={_format_value(sort_value)}；硬过滤均通过。"
    )


def _risk_tips(row_values: Mapping[str, object], display_factors: Sequence[str]) -> str:
    risks: list[str] = []
    missing_display = [
        factor_name
        for factor_name in display_factors
        if _is_missing(row_values.get(factor_name, pd.NA))
    ]
    if missing_display:
        risks.append("展示因子缺失：" + ", ".join(missing_display))

    if _numeric_value(row_values.get("pe_ttm_percentile")) is not None:
        if _numeric_value(row_values.get("pe_ttm_percentile")) >= 0.8:  # type: ignore[operator]
            risks.append("估值处于自身历史高位")
    if _numeric_value(row_values.get("pb_percentile")) is not None:
        if _numeric_value(row_values.get("pb_percentile")) >= 0.8:  # type: ignore[operator]
            risks.append("PB 处于自身历史高位")
    if _numeric_value(row_values.get("return_20d")) is not None:
        if _numeric_value(row_values.get("return_20d")) < 0:  # type: ignore[operator]
            risks.append("20 日动量为负")
    if _numeric_value(row_values.get("return_60d")) is not None:
        if _numeric_value(row_values.get("return_60d")) < 0:  # type: ignore[operator]
            risks.append("60 日动量为负")

    above_ma60 = _numeric_value(row_values.get("above_ma60"))
    if above_ma60 is not None and above_ma60 == 0.0:
        risks.append("价格低于 60 日均线")

    return "；".join(risks) if risks else NO_RISK_TEXT


def _numeric_value(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _format_value(value: object) -> str:
    numeric = _numeric_value(value)
    if numeric is None:
        return ""
    return f"{numeric:.4f}"


def _display_factor_names(
    sort_factor: str,
    requested: Sequence[str] | None,
    factor_metadata: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    if requested:
        deduped = tuple(dict.fromkeys(str(name) for name in requested))
        for factor_name in deduped:
            _validate_factor_name(factor_name, factor_metadata, option_name="factor")
        remaining = [name for name in deduped if name != sort_factor]
        return (sort_factor, *remaining)

    factor_names = sorted(
        name for name, entry in factor_metadata.items() if str(entry.get("type")) == "factor"
    )
    remaining = [name for name in factor_names if name != sort_factor]
    return (sort_factor, *remaining)


def _validate_factor_name(
    factor_name: str,
    factor_metadata: Mapping[str, Mapping[str, object]],
    option_name: str,
) -> None:
    if factor_name not in factor_metadata:
        raise ValueError(f"Unknown factor name for {option_name}: {factor_name}")
    factor_type = str(factor_metadata[factor_name].get("type"))
    if factor_type != "factor":
        raise ValueError(f"{option_name} must reference a type: factor entry: {factor_name}")


def _factor_direction(
    factor_metadata: Mapping[str, Mapping[str, object]],
    factor_name: str,
) -> str:
    direction = factor_metadata[factor_name].get("direction")
    if not isinstance(direction, str):
        raise ValueError(f"Missing direction for factor: {factor_name}")
    return direction


def _factor_metadata(data_dictionary: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    factors = data_dictionary.get("factors")
    if not isinstance(factors, Mapping):
        raise ValueError("data_dictionary.factors must be a mapping.")
    metadata: dict[str, Mapping[str, object]] = {}
    for name, entry in factors.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"data_dictionary.factors.{name} must be a mapping.")
        metadata[str(name)] = entry
    return metadata
