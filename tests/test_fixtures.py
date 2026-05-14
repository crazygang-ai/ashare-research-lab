import csv
from pathlib import Path

from ashare.fixtures.builder import CSV_FILES, MAIN_SAMPLE_DAYS, build_fixtures


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_fixture_builder_creates_all_expected_csv_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"

    build_fixtures(output_dir)

    for filename in CSV_FILES:
        assert (output_dir / filename).is_file()


def test_fixture_calendar_has_main_sample_and_buffer_days(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    build_fixtures(output_dir)

    calendar_rows = _read_csv(output_dir / "trading_calendar.csv")
    daily_price_rows = _read_csv(output_dir / "daily_prices.csv")
    calendar_dates = [row["trade_date"] for row in calendar_rows]
    price_dates = sorted({row["trade_date"] for row in daily_price_rows})

    assert len(calendar_rows) >= MAIN_SAMPLE_DAYS + 3
    assert calendar_dates[0] == "2026-01-05"
    assert len(price_dates) == MAIN_SAMPLE_DAYS
    assert price_dates == calendar_dates[:MAIN_SAMPLE_DAYS]


def test_fixture_securities_include_five_stocks_and_one_delist(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    build_fixtures(output_dir)

    rows = _read_csv(output_dir / "securities.csv")

    assert len(rows) == 5
    assert sum(1 for row in rows if row["delist_date"]) == 1


def test_fixture_st_suspend_and_limit_edge_cases(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    build_fixtures(output_dir)

    st_rows = _read_csv(output_dir / "st_status.csv")
    price_rows = _read_csv(output_dir / "daily_prices.csv")

    assert any(row["st_type"] == "ST" for row in st_rows)
    assert any(row["is_suspended"] == "true" for row in price_rows)
    assert any(
        row["limit_up"] and float(row["close"]) == float(row["limit_up"])
        for row in price_rows
    )
    assert any(
        row["limit_down"] and float(row["close"]) == float(row["limit_down"])
        for row in price_rows
    )


def test_fixture_fundamental_announcement_and_risk_coverage(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    build_fixtures(output_dir)

    fundamental_rows = _read_csv(output_dir / "fundamental_reports.csv")
    announcement_rows = _read_csv(output_dir / "announcements.csv")
    risk_rows = _read_csv(output_dir / "risk_events.csv")

    for column in {"goodwill", "total_equity", "accounts_receivable", "inventory"}:
        assert any(row[column] for row in fundamental_rows)

    assert {"earnings_forecast", "buyback", "inquiry_letter"}.issubset(
        {row["announcement_type"] for row in announcement_rows}
    )
    assert {"pledge", "shareholder_reduce", "inquiry_letter", "non_standard_audit"}.issubset(
        {row["event_type"] for row in risk_rows}
    )
