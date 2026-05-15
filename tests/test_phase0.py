from pathlib import Path
import subprocess

import duckdb
import typer

from ashare.cli import app


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILES = [
    "universe.yaml",
    "data.yaml",
    "data_dictionary.yaml",
    "factors.yaml",
    "validation.yaml",
    "backtest.yaml",
    "scoring.yaml",
    "llm.yaml",
]
CLI_COMMANDS = [
    "ingest",
    "validate-factors",
    "event-study",
    "scan",
    "backtest",
    "report",
    "stock-report",
    "db-init",
    "ingest-local",
    "as-of",
    "calculate-factors",
]
SCHEMA_TABLES = [
    "trading_calendar",
    "securities",
    "industry_classifications",
    "universe_members",
    "daily_prices",
    "st_status",
    "fundamental_reports",
    "valuation_daily",
    "announcements",
    "risk_events",
    "factor_values",
    "research_runs",
]


def test_cli_imports_and_app_exists() -> None:
    assert isinstance(app, typer.Typer)


def test_cli_help_lists_phase0_commands() -> None:
    result = subprocess.run(
        ["ashare", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    for command in CLI_COMMANDS:
        assert command in result.stdout


def test_required_config_files_exist() -> None:
    for filename in CONFIG_FILES:
        assert (ROOT / "configs" / filename).is_file()


def test_schema_exists_and_executes_in_duckdb() -> None:
    schema_path = ROOT / "src" / "ashare" / "storage" / "schema.sql"
    assert schema_path.is_file()

    connection = duckdb.connect(":memory:")
    try:
        connection.execute(schema_path.read_text(encoding="utf-8"))
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    finally:
        connection.close()

    assert set(SCHEMA_TABLES).issubset(tables)
