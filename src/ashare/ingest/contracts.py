"""Dataset normalization and field contracts for Phase 1a-7 ingest."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd


@dataclass(frozen=True)
class FieldValidationIssue:
    """A field-contract issue emitted by normalization or validation."""

    dataset: str
    severity: str
    code: str
    message: str
    row_count: int | None = None


class FieldValidationError(ValueError):
    """Raised when a dataset violates a hard field contract."""

    def __init__(self, issues: tuple[FieldValidationIssue, ...]) -> None:
        self.issues = issues
        message = "; ".join(issue.message for issue in issues if issue.severity == "error")
        super().__init__(message or "Dataset field validation failed.")


DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    "trading_calendar": ("trade_date", "is_open", "prev_trade_date", "next_trade_date"),
    "securities": (
        "stock_code",
        "stock_name",
        "exchange",
        "list_date",
        "delist_date",
        "delist_publish_time",
        "delist_effective_date",
    ),
    "universe_members": (
        "index_code",
        "stock_code",
        "in_date",
        "out_date",
        "in_publish_time",
        "in_effective_date",
        "out_publish_time",
        "out_effective_date",
        "source",
    ),
    "daily_prices": (
        "stock_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "is_suspended",
        "limit_up",
        "limit_down",
    ),
    "valuation_daily": (
        "stock_code",
        "trade_date",
        "pe_ttm",
        "pb",
        "ps",
        "dividend_yield",
        "total_mv",
        "float_mv",
        "source",
    ),
}

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "trading_calendar": ("trade_date", "is_open"),
    "securities": ("stock_code", "exchange", "list_date"),
    "universe_members": ("index_code", "stock_code", "in_date", "in_effective_date", "source"),
    "daily_prices": ("stock_code", "trade_date", "open", "high", "low", "close", "volume", "amount"),
    "valuation_daily": ("stock_code", "trade_date", "pe_ttm", "pb", "source"),
}

KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "trading_calendar": ("trade_date",),
    "securities": ("stock_code",),
    "universe_members": ("index_code", "stock_code", "in_date"),
    "daily_prices": ("stock_code", "trade_date"),
    "valuation_daily": ("source", "stock_code", "trade_date"),
}

DATE_COLUMNS = {
    "trade_date",
    "prev_trade_date",
    "next_trade_date",
    "list_date",
    "delist_date",
    "delist_effective_date",
    "in_date",
    "out_date",
    "in_effective_date",
    "out_effective_date",
}
TIMESTAMP_COLUMNS = {"delist_publish_time", "in_publish_time", "out_publish_time"}
BOOL_COLUMNS = {"is_open", "is_suspended"}
INT_COLUMNS = {"volume"}
FLOAT_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "amount",
    "adj_factor",
    "limit_up",
    "limit_down",
    "pe_ttm",
    "pb",
    "ps",
    "dividend_yield",
    "total_mv",
    "float_mv",
}

OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "trading_calendar": ("prev_trade_date", "next_trade_date"),
    "securities": (
        "stock_name",
        "delist_date",
        "delist_publish_time",
        "delist_effective_date",
    ),
    "universe_members": ("out_date", "in_publish_time", "out_publish_time", "out_effective_date"),
    "daily_prices": ("adj_factor", "is_suspended", "limit_up", "limit_down"),
    "valuation_daily": ("ps", "dividend_yield", "total_mv", "float_mv"),
}

COLUMN_ALIASES: dict[str, dict[str, str]] = {
    "trading_calendar": {
        "trade_date": "trade_date",
        "tradedate": "trade_date",
        "cal_date": "trade_date",
        "date": "trade_date",
        "日期": "trade_date",
        "交易日期": "trade_date",
        "is_open": "is_open",
        "isopen": "is_open",
        "是否交易": "is_open",
        "prev_trade_date": "prev_trade_date",
        "pretrade_date": "prev_trade_date",
        "next_trade_date": "next_trade_date",
    },
    "securities": {
        "stock_code": "stock_code",
        "stockcode": "stock_code",
        "symbol": "stock_code",
        "code": "stock_code",
        "证券代码": "stock_code",
        "股票代码": "stock_code",
        "成分券代码": "stock_code",
        "品种代码": "stock_code",
        "stock_name": "stock_name",
        "stockname": "stock_name",
        "name": "stock_name",
        "证券简称": "stock_name",
        "股票简称": "stock_name",
        "成分券名称": "stock_name",
        "名称": "stock_name",
        "exchange": "exchange",
        "交易所": "exchange",
        "list_date": "list_date",
        "上市日期": "list_date",
        "delist_date": "delist_date",
        "退市日期": "delist_date",
        "delist_publish_time": "delist_publish_time",
        "delist_effective_date": "delist_effective_date",
    },
    "universe_members": {
        "index_code": "index_code",
        "indexcode": "index_code",
        "指数代码": "index_code",
        "stock_code": "stock_code",
        "stockcode": "stock_code",
        "symbol": "stock_code",
        "code": "stock_code",
        "成分券代码": "stock_code",
        "品种代码": "stock_code",
        "证券代码": "stock_code",
        "股票代码": "stock_code",
        "stock_name": "stock_name",
        "stockname": "stock_name",
        "成分券名称": "stock_name",
        "证券简称": "stock_name",
        "股票简称": "stock_name",
        "in_date": "in_date",
        "纳入日期": "in_date",
        "out_date": "out_date",
        "剔除日期": "out_date",
        "in_publish_time": "in_publish_time",
        "in_effective_date": "in_effective_date",
        "out_publish_time": "out_publish_time",
        "out_effective_date": "out_effective_date",
        "source": "source",
    },
    "daily_prices": {
        "stock_code": "stock_code",
        "stockcode": "stock_code",
        "symbol": "stock_code",
        "code": "stock_code",
        "股票代码": "stock_code",
        "证券代码": "stock_code",
        "trade_date": "trade_date",
        "tradedate": "trade_date",
        "date": "trade_date",
        "日期": "trade_date",
        "开盘": "open",
        "开盘价": "open",
        "open": "open",
        "最高": "high",
        "最高价": "high",
        "high": "high",
        "最低": "low",
        "最低价": "low",
        "low": "low",
        "收盘": "close",
        "收盘价": "close",
        "close": "close",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
        "adj_factor": "adj_factor",
        "复权因子": "adj_factor",
        "is_suspended": "is_suspended",
        "停牌": "is_suspended",
        "limit_up": "limit_up",
        "涨停": "limit_up",
        "limit_down": "limit_down",
        "跌停": "limit_down",
    },
    "valuation_daily": {
        "stock_code": "stock_code",
        "stockcode": "stock_code",
        "symbol": "stock_code",
        "code": "stock_code",
        "股票代码": "stock_code",
        "证券代码": "stock_code",
        "trade_date": "trade_date",
        "tradedate": "trade_date",
        "date": "trade_date",
        "日期": "trade_date",
        "pe_ttm": "pe_ttm",
        "市盈率ttm": "pe_ttm",
        "市盈率TTM": "pe_ttm",
        "pb": "pb",
        "市净率": "pb",
        "ps": "ps",
        "市销率": "ps",
        "dividend_yield": "dividend_yield",
        "股息率": "dividend_yield",
        "total_mv": "total_mv",
        "总市值": "total_mv",
        "float_mv": "float_mv",
        "流通市值": "float_mv",
        "source": "source",
    },
}


def normalize_dataset(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize aliases, types, stock codes, and drop contract-external columns."""
    _ensure_known_dataset(dataset)
    normalized = _rename_columns(dataset, frame.copy())
    expected = DATASET_COLUMNS[dataset]

    if dataset == "trading_calendar" and "is_open" not in normalized:
        normalized["is_open"] = True
    for column in OPTIONAL_COLUMNS.get(dataset, ()):
        if column not in normalized:
            normalized[column] = pd.NA

    if "stock_code" in normalized:
        normalized["stock_code"] = normalized["stock_code"].map(normalize_stock_code)
    if "index_code" in normalized:
        normalized["index_code"] = normalized["index_code"].map(normalize_index_code)
    if dataset == "securities":
        if "exchange" not in normalized and "stock_code" in normalized:
            normalized["exchange"] = normalized["stock_code"].map(exchange_from_stock_code)
        elif "exchange" in normalized:
            missing_exchange = normalized["exchange"].isna() | (
                normalized["exchange"].astype("string").str.strip() == ""
            )
            if "stock_code" in normalized and missing_exchange.any():
                normalized.loc[missing_exchange, "exchange"] = normalized.loc[
                    missing_exchange, "stock_code"
                ].map(exchange_from_stock_code)

    for column in list(normalized.columns):
        if column in DATE_COLUMNS:
            normalized[column] = _to_date_series(dataset, column, normalized[column])
        elif column in TIMESTAMP_COLUMNS:
            normalized[column] = _to_timestamp_series(dataset, column, normalized[column])
        elif column in BOOL_COLUMNS:
            normalized[column] = normalized[column].map(_to_bool)
        elif column in INT_COLUMNS:
            normalized[column] = _to_numeric_series(dataset, column, normalized[column]).astype(
                "Int64"
            )
        elif column in FLOAT_COLUMNS:
            normalized[column] = _to_numeric_series(dataset, column, normalized[column])

    if dataset == "trading_calendar":
        normalized = _fill_calendar_neighbors(normalized)

    selected = [column for column in expected if column in normalized]
    return normalized[selected].copy()


def validate_dataset(
    dataset: str,
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[FieldValidationIssue, ...]]:
    """Validate one normalized dataset and return warnings, raising on hard failures."""
    _ensure_known_dataset(dataset)
    issues: list[FieldValidationIssue] = []
    working = frame.copy()

    missing = [column for column in REQUIRED_COLUMNS[dataset] if column not in working.columns]
    if missing:
        issues.append(
            FieldValidationIssue(
                dataset=dataset,
                severity="error",
                code="missing_required_columns",
                message=f"{dataset} missing required columns: {', '.join(missing)}",
                row_count=None,
            )
        )

    for column in DATASET_COLUMNS[dataset]:
        if column not in working.columns:
            working[column] = pd.NA

    for column in REQUIRED_COLUMNS[dataset]:
        if column in working.columns:
            missing_values = int(_missing_mask(working[column]).sum())
            if missing_values:
                issues.append(
                    FieldValidationIssue(
                        dataset=dataset,
                        severity="error",
                        code="missing_required_values",
                        message=f"{dataset}.{column} has missing required values.",
                        row_count=missing_values,
                    )
                )

    key_columns = KEY_COLUMNS[dataset]
    if set(key_columns).issubset(working.columns):
        duplicate_rows = int(working.duplicated(list(key_columns), keep=False).sum())
        if duplicate_rows:
            issues.append(
                FieldValidationIssue(
                    dataset=dataset,
                    severity="error",
                    code="duplicate_key",
                    message=f"{dataset} has duplicate key rows on {key_columns}.",
                    row_count=duplicate_rows,
                )
            )

    if dataset == "daily_prices":
        issues.extend(_validate_daily_prices(working))
    elif dataset == "valuation_daily":
        issues.extend(_validate_valuation_daily(working))

    errors = tuple(issue for issue in issues if issue.severity == "error")
    if errors:
        raise FieldValidationError(tuple(issues))

    ordered = working.loc[:, DATASET_COLUMNS[dataset]].copy()
    return ordered, tuple(issues)


def normalize_stock_code(value: object) -> str | None:
    """Canonicalize common A-share code representations to ``000001.SZ`` form."""
    if _is_missing_scalar(value):
        return None
    raw = str(value).strip().upper()
    if raw == "":
        return None
    raw = raw.replace("_", ".")

    match = re.fullmatch(r"([0-9]{6})\.(SH|SZ|BJ)", raw)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    match = re.fullmatch(r"(SH|SZ|BJ)([0-9]{6})", raw)
    if match:
        return f"{match.group(2)}.{match.group(1)}"

    match = re.fullmatch(r"([0-9]{6})(SH|SZ|BJ)", raw)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    if re.fullmatch(r"[0-9]{6}", raw):
        if raw.startswith("6"):
            return f"{raw}.SH"
        if raw.startswith(("0", "3")):
            return f"{raw}.SZ"
        if raw.startswith(("4", "8", "9")):
            return f"{raw}.BJ"
    return None


def normalize_index_code(value: object) -> str | None:
    """Canonicalize known index codes while preserving local fixture aliases."""
    if _is_missing_scalar(value):
        return None
    raw = str(value).strip().upper()
    if raw == "":
        return None
    raw = raw.replace("_", ".")
    if re.fullmatch(r"[0-9]{6}", raw):
        return f"{raw}.SH"
    if re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", raw):
        return raw
    return str(value).strip()


def exchange_from_stock_code(stock_code: object) -> str | None:
    """Derive a compact exchange label from canonical stock-code suffixes."""
    if _is_missing_scalar(stock_code):
        return None
    raw = str(stock_code).upper()
    if raw.endswith(".SH"):
        return "SHSE"
    if raw.endswith(".SZ"):
        return "SZSE"
    if raw.endswith(".BJ"):
        return "BSE"
    return None


def duplicate_key_count(dataset: str, frame: pd.DataFrame) -> int:
    """Return duplicate key row count for reports."""
    key_columns = KEY_COLUMNS[dataset]
    if not set(key_columns).issubset(frame.columns):
        return 0
    return int(frame.duplicated(list(key_columns), keep=False).sum())


def _ensure_known_dataset(dataset: str) -> None:
    if dataset not in DATASET_COLUMNS:
        raise ValueError(f"Unsupported dataset: {dataset}")


def _rename_columns(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    aliases = COLUMN_ALIASES[dataset]
    rename: dict[str, str] = {}
    used: set[str] = set()
    for column in frame.columns:
        key = _alias_key(str(column))
        canonical = aliases.get(key, aliases.get(str(column).strip(), str(column).strip()))
        if canonical in DATASET_COLUMNS[dataset] and canonical not in used:
            rename[column] = canonical
            used.add(canonical)
    return frame.rename(columns=rename)


def _alias_key(value: str) -> str:
    return value.strip().replace(" ", "").replace("-", "_").lower()


def _to_date_series(dataset: str, column: str, series: pd.Series) -> pd.Series:
    mask = ~_missing_mask(series)
    parsed = pd.to_datetime(series, errors="coerce")
    bad = mask & parsed.isna()
    if bool(bad.any()):
        raise ValueError(f"{dataset}.{column} contains unparseable dates.")
    return parsed.dt.date.where(mask, None)


def _to_timestamp_series(dataset: str, column: str, series: pd.Series) -> pd.Series:
    mask = ~_missing_mask(series)
    parsed = pd.to_datetime(series, errors="coerce")
    bad = mask & parsed.isna()
    if bool(bad.any()):
        raise ValueError(f"{dataset}.{column} contains unparseable timestamps.")
    return parsed.where(mask, None)


def _to_numeric_series(dataset: str, column: str, series: pd.Series) -> pd.Series:
    mask = ~_missing_mask(series)
    parsed = pd.to_numeric(series, errors="coerce")
    bad = mask & parsed.isna()
    if bool(bad.any()):
        raise ValueError(f"{dataset}.{column} contains non-numeric values.")
    return parsed


def _to_bool(value: object) -> bool | None:
    if _is_missing_scalar(value):
        return None
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y", "是", "开市", "交易"}:
        return True
    if raw in {"false", "0", "no", "n", "否", "休市", "停牌"}:
        return False
    return None


def _fill_calendar_neighbors(frame: pd.DataFrame) -> pd.DataFrame:
    if "trade_date" not in frame.columns or frame.empty:
        return frame
    sorted_frame = frame.sort_values("trade_date").copy()
    open_dates = sorted_frame.loc[sorted_frame["is_open"].fillna(False), "trade_date"].tolist()
    if "prev_trade_date" in sorted_frame.columns:
        missing_prev = _missing_mask(sorted_frame["prev_trade_date"])
    else:
        sorted_frame["prev_trade_date"] = pd.NA
        missing_prev = pd.Series(True, index=sorted_frame.index)
    if "next_trade_date" in sorted_frame.columns:
        missing_next = _missing_mask(sorted_frame["next_trade_date"])
    else:
        sorted_frame["next_trade_date"] = pd.NA
        missing_next = pd.Series(True, index=sorted_frame.index)

    prev_by_date = {trade_date: open_dates[index - 1] if index > 0 else None for index, trade_date in enumerate(open_dates)}
    next_by_date = {
        trade_date: open_dates[index + 1] if index + 1 < len(open_dates) else None
        for index, trade_date in enumerate(open_dates)
    }
    sorted_frame.loc[missing_prev, "prev_trade_date"] = sorted_frame.loc[
        missing_prev, "trade_date"
    ].map(prev_by_date)
    sorted_frame.loc[missing_next, "next_trade_date"] = sorted_frame.loc[
        missing_next, "trade_date"
    ].map(next_by_date)
    return sorted_frame


def _validate_daily_prices(frame: pd.DataFrame) -> list[FieldValidationIssue]:
    issues: list[FieldValidationIssue] = []
    high_low = frame["high"] < frame["low"]
    if bool(high_low.any()):
        issues.append(
            FieldValidationIssue(
                dataset="daily_prices",
                severity="error",
                code="high_below_low",
                message="daily_prices.high is below low.",
                row_count=int(high_low.sum()),
            )
        )
    close_outside = (frame["close"] < frame["low"]) | (frame["close"] > frame["high"])
    if bool(close_outside.any()):
        issues.append(
            FieldValidationIssue(
                dataset="daily_prices",
                severity="error",
                code="close_outside_high_low",
                message="daily_prices.close is outside [low, high].",
                row_count=int(close_outside.sum()),
            )
        )
    negative_volume = frame["volume"] < 0
    if bool(negative_volume.any()):
        issues.append(
            FieldValidationIssue(
                dataset="daily_prices",
                severity="error",
                code="negative_volume",
                message="daily_prices.volume is negative.",
                row_count=int(negative_volume.sum()),
            )
        )
    negative_amount = frame["amount"] < 0
    if bool(negative_amount.any()):
        issues.append(
            FieldValidationIssue(
                dataset="daily_prices",
                severity="error",
                code="negative_amount",
                message="daily_prices.amount is negative.",
                row_count=int(negative_amount.sum()),
            )
        )
    for column, code in [
        ("adj_factor", "missing_adj_factor"),
        ("limit_up", "missing_limit_up"),
        ("limit_down", "missing_limit_down"),
    ]:
        missing = int(_missing_mask(frame[column]).sum())
        if missing:
            issues.append(
                FieldValidationIssue(
                    dataset="daily_prices",
                    severity="warning",
                    code=code,
                    message=f"daily_prices.{column} has missing values.",
                    row_count=missing,
                )
            )
    missing_suspended = int(_missing_mask(frame["is_suspended"]).sum())
    if missing_suspended:
        issues.append(
            FieldValidationIssue(
                dataset="daily_prices",
                severity="warning",
                code="is_suspended_unreliable",
                message="daily_prices.is_suspended is missing or not reliably sourced.",
                row_count=missing_suspended,
            )
        )
    return issues


def _validate_valuation_daily(frame: pd.DataFrame) -> list[FieldValidationIssue]:
    issues: list[FieldValidationIssue] = []
    pe_non_positive = frame["pe_ttm"] <= 0
    if bool(pe_non_positive.any()):
        issues.append(
            FieldValidationIssue(
                dataset="valuation_daily",
                severity="warning",
                code="non_positive_pe_ttm",
                message="valuation_daily.pe_ttm contains non-positive values.",
                row_count=int(pe_non_positive.sum()),
            )
        )
    pb_non_positive = frame["pb"] <= 0
    if bool(pb_non_positive.any()):
        issues.append(
            FieldValidationIssue(
                dataset="valuation_daily",
                severity="warning",
                code="non_positive_pb",
                message="valuation_daily.pb contains non-positive values.",
                row_count=int(pb_non_positive.sum()),
            )
        )
    return issues


def _missing_mask(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype("string").str.strip() == "")


def _is_missing_scalar(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, pd.Timestamp):
        return pd.isna(value)
    if isinstance(value, float) and pd.isna(value):
        return True
    return value is pd.NA
