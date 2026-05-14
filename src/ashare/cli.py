"""Command-line interface for ashare-research-lab."""

from pathlib import Path
from typing import Any

import typer

from ashare.fixtures.builder import build_fixtures as build_fixture_csvs
from ashare.ingest.local import ingest_local as ingest_local_csvs
from ashare.pit.asof import AsOfSnapshot, load_as_of_snapshot, parse_as_of_date
from ashare.storage.db import default_schema_path, init_db

app = typer.Typer(help="A-share research assistant CLI.")


def _echo_todo(command: str, **params: Any) -> None:
    typer.echo(f"{command}: TODO")
    typer.echo(f"params: {params}")


def _joined_stock_codes(values: list[str]) -> str:
    return ", ".join(values) if values else "(empty)"


def _print_as_of_snapshot(snapshot: AsOfSnapshot) -> None:
    typer.echo(f"as_of_date: {snapshot.as_of_date.isoformat()}")
    typer.echo("Rows:")
    for name in [
        "daily_prices",
        "valuation_daily",
        "universe_members",
        "securities",
        "st_status",
        "industry_classifications",
        "fundamental_reports",
        "announcements",
        "risk_events",
    ]:
        typer.echo(f"  {name}: {len(getattr(snapshot, name))}")

    universe_codes = snapshot.universe_members["stock_code"].tolist()
    securities_codes = snapshot.securities["stock_code"].tolist()
    typer.echo(f"universe_stock_codes: {_joined_stock_codes(universe_codes)}")
    typer.echo(f"securities_stock_codes: {_joined_stock_codes(securities_codes)}")

    if "is_delisted_as_of" in snapshot.securities.columns:
        delisted_codes = snapshot.securities.loc[
            snapshot.securities["is_delisted_as_of"], "stock_code"
        ].tolist()
        typer.echo(f"delisted_stock_codes: {_joined_stock_codes(delisted_codes)}")


@app.command(name="ingest")
def ingest(
    universe: str = typer.Option("hs300", "--universe"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
) -> None:
    """Print ingest parameters without fetching data."""
    _echo_todo("ingest", universe=universe, from_=from_, to=to)


@app.command(name="validate-factors")
def validate_factors(
    universe: str = typer.Option("hs300", "--universe"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    horizon: str = typer.Option("20,60,120", "--horizon"),
) -> None:
    """Print factor-validation parameters without calculating factors."""
    _echo_todo("validate-factors", universe=universe, from_=from_, to=to, horizon=horizon)


@app.command(name="event-study")
def event_study(
    event: str = typer.Option(..., "--event"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    horizon: str = typer.Option("5,20,60", "--horizon"),
) -> None:
    """Print event-study parameters without running an event study."""
    _echo_todo("event-study", event=event, from_=from_, to=to, horizon=horizon)


@app.command(name="scan")
def scan(
    as_of: str = typer.Option(..., "--as-of"),
    universe: str = typer.Option("hs300", "--universe"),
    top: int = typer.Option(20, "--top"),
) -> None:
    """Print scan parameters without generating candidates."""
    _echo_todo("scan", as_of=as_of, universe=universe, top=top)


@app.command(name="backtest")
def backtest(
    strategy: str = typer.Option("base_score", "--strategy"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
) -> None:
    """Print backtest parameters without running a backtest."""
    _echo_todo("backtest", strategy=strategy, from_=from_, to=to)


@app.command(name="report")
def report(as_of: str = typer.Option(..., "--as-of")) -> None:
    """Print report parameters without writing reports."""
    _echo_todo("report", as_of=as_of)


@app.command(name="stock-report")
def stock_report(
    code: str = typer.Option(..., "--code"),
    as_of: str = typer.Option(..., "--as-of"),
) -> None:
    """Print stock-report parameters without writing reports."""
    _echo_todo("stock-report", code=code, as_of=as_of)


@app.command(name="db-init")
def db_init(
    db_path: str = typer.Option("data/processed/ashare.duckdb", "--db-path"),
    schema_path: str | None = typer.Option(None, "--schema-path"),
) -> None:
    """Initialize the DuckDB database schema."""
    resolved_schema_path = default_schema_path() if schema_path is None else schema_path
    init_db(db_path=db_path, schema_path=schema_path)
    typer.echo(f"Initialized DuckDB database: {db_path}")
    typer.echo(f"Schema path: {resolved_schema_path}")


@app.command(name="ingest-local")
def ingest_local(
    input_dir: Path = typer.Option(Path("tests/fixtures/generated"), "--input-dir"),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    build_fixtures: bool = typer.Option(
        True,
        "--build-fixtures/--no-build-fixtures",
    ),
) -> None:
    """Build optional local fixtures, then clear and rewrite fixture tables."""
    if build_fixtures:
        build_fixture_csvs(input_dir)

    summary = ingest_local_csvs(input_dir=input_dir, db_path=db_path)
    typer.echo("Local fixture ingest completed.")
    typer.echo("WARNING: ingest-local clears target tables before rewriting fixture data.")
    typer.echo(f"Input dir: {input_dir}")
    typer.echo(f"Database path: {db_path}")
    typer.echo("Rows loaded:")
    for table, row_count in summary.items():
        typer.echo(f"  {table}: {row_count}")


@app.command(name="as-of")
def as_of(
    as_of: str = typer.Option(..., "--as-of", help="Explicit ISO as-of date, e.g. 2026-01-12."),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    index_code: str | None = typer.Option(None, "--index-code"),
    industry_standard: str | None = typer.Option(None, "--industry-standard"),
    industry_version: str | None = typer.Option(None, "--industry-version"),
    include_delisted: bool = typer.Option(False, "--include-delisted"),
    stock_code: str | None = typer.Option(None, "--stock-code"),
) -> None:
    """Print visible PIT row counts and stock-code coverage for one as-of date."""
    try:
        parsed_date = parse_as_of_date(as_of)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--as-of") from exc

    snapshot = load_as_of_snapshot(
        db_path=db_path,
        as_of_date=parsed_date,
        index_code=index_code,
        industry_standard=industry_standard,
        industry_version=industry_version,
        include_delisted=include_delisted,
        stock_code=stock_code,
    )
    _print_as_of_snapshot(snapshot)
