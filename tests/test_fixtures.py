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
    delist_row = next(row for row in rows if row["stock_code"] == "000003.SZ")

    assert len(rows) == 5
    assert sum(1 for row in rows if row["delist_date"]) == 1
    assert delist_row["delist_publish_time"] == "2026-03-02 18:00:00"
    assert delist_row["delist_effective_date"] == "2026-03-03"


def test_fixture_interval_csvs_include_visibility_fields(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    build_fixtures(output_dir)

    securities = _read_csv(output_dir / "securities.csv")
    universe = _read_csv(output_dir / "universe_members.csv")
    st_rows = _read_csv(output_dir / "st_status.csv")
    industry_rows = _read_csv(output_dir / "industry_classifications.csv")

    assert {"delist_publish_time", "delist_effective_date"}.issubset(securities[0])
    for rows in [universe, st_rows, industry_rows]:
        assert {
            "in_publish_time",
            "in_effective_date",
            "out_publish_time",
            "out_effective_date",
        }.issubset(rows[0])

    delist_member = next(row for row in universe if row["stock_code"] == "000003.SZ")
    st_row = st_rows[0]
    industry_switch = [row for row in industry_rows if row["stock_code"] == "000005.SZ"]

    assert delist_member["out_publish_time"] == "2026-03-02 18:00:00"
    assert delist_member["out_effective_date"] == "2026-03-03"
    assert st_row["in_publish_time"] == "2026-01-20 18:00:00"
    assert st_row["in_effective_date"] == "2026-01-21"
    assert st_row["out_publish_time"] == "2026-02-16 18:00:00"
    assert st_row["out_effective_date"] == "2026-02-17"
    assert len(industry_switch) == 2
    assert industry_switch[0]["industry_l2"] == "Software"
    assert industry_switch[0]["out_publish_time"] == "2026-02-12 18:00:00"
    assert industry_switch[0]["out_effective_date"] == "2026-02-13"
    assert industry_switch[1]["industry_l2"] == "Internet"
    assert industry_switch[1]["in_publish_time"] == "2026-02-12 18:00:00"
    assert industry_switch[1]["in_effective_date"] == "2026-02-13"


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
