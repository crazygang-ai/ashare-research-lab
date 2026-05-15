"""Command-line interface for ashare-research-lab."""

from pathlib import Path
from typing import Any

import duckdb
import click
import typer

from ashare.factors.calculator import (
    SUPPORTED_FACTORS,
    calculate_factors_for_date,
    open_trading_dates_between,
)
from ashare.factors.config import load_factor_config
from ashare.factors.store import write_factor_values
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


def _factor_row_counts(factors: Any) -> dict[str, int]:
    if factors.empty:
        return {name: 0 for name in SUPPORTED_FACTORS}

    counts = factors.groupby("factor_name").size().to_dict()
    return {name: int(counts.get(name, 0)) for name in SUPPORTED_FACTORS}


def _print_factor_counts(counts: dict[str, int]) -> None:
    typer.echo("factor_rows:")
    for factor_name in SUPPORTED_FACTORS:
        typer.echo(f"  {factor_name}: {counts.get(factor_name, 0)}")


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


@app.command(name="calculate-factors")
def calculate_factors(
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    as_of: str | None = typer.Option(None, "--as-of", help="Single trading date in ISO format."),
    from_: str | None = typer.Option(
        None,
        "--from",
        help="Inclusive range start. Endpoints may be non-trading days.",
    ),
    to: str | None = typer.Option(
        None,
        "--to",
        help="Inclusive range end. Endpoints may be non-trading days.",
    ),
    index_code: str | None = typer.Option(None, "--index-code"),
    factor: list[str] | None = typer.Option(None, "--factor"),
    factor_config: Path = typer.Option(Path("configs/factors.yaml"), "--factor-config"),
    source_run_id: str = typer.Option("phase1a4", "--source-run-id"),
    include_delisted: bool = typer.Option(False, "--include-delisted"),
    replace: bool = typer.Option(True, "--replace/--append"),
) -> None:
    """Calculate and store Phase 1a-4 factors. Range output prints per-date universe sizes."""
    has_as_of = as_of is not None
    has_from = from_ is not None
    has_to = to is not None

    if has_as_of and (has_from or has_to):
        raise click.ClickException("--as-of is mutually exclusive with --from/--to.")
    if not has_as_of and not (has_from or has_to):
        raise click.ClickException(
            "Choose single-date mode (--as-of) or range mode (--from and --to)."
        )
    if (has_from and not has_to) or (has_to and not has_from):
        raise click.ClickException("Range mode requires both --from and --to.")

    try:
        parsed_config = load_factor_config(factor_config)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    init_db(db_path)
    connection = duckdb.connect(str(db_path))
    try:
        if has_as_of:
            assert as_of is not None
            try:
                parsed_as_of = parse_as_of_date(as_of)
                factors = calculate_factors_for_date(
                    connection=connection,
                    as_of_date=parsed_as_of,
                    index_code=index_code,
                    factor_names=factor,
                    include_delisted=include_delisted,
                    factor_config=parsed_config,
                )
            except (TypeError, ValueError) as exc:
                raise click.ClickException(str(exc)) from exc

            written_rows = write_factor_values(
                connection,
                factors,
                source_run_id=source_run_id,
                replace=replace,
            )
            typer.echo(f"Database path: {db_path}")
            typer.echo(f"Date mode: as-of {parsed_as_of.isoformat()}")
            typer.echo(f"source_run_id: {source_run_id}")
            typer.echo(f"universe_size: {factors.attrs.get('universe_size', 0)}")
            typer.echo(f"written_rows: {written_rows}")
            _print_factor_counts(_factor_row_counts(factors))
            return

        assert from_ is not None and to is not None
        try:
            start = parse_as_of_date(from_)
            end = parse_as_of_date(to)
            trading_dates = open_trading_dates_between(connection, start, end)
        except (TypeError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc

        frames = []
        universe_sizes: dict[str, int] = {}
        for trading_date in trading_dates:
            factors_for_date = calculate_factors_for_date(
                connection=connection,
                as_of_date=trading_date,
                index_code=index_code,
                factor_names=factor,
                include_delisted=include_delisted,
                factor_config=parsed_config,
            )
            universe_sizes[trading_date.isoformat()] = int(
                factors_for_date.attrs.get("universe_size", 0)
            )
            frames.append(factors_for_date)

        if frames:
            import pandas as pd

            factors = pd.concat(frames, ignore_index=True)
        else:
            import pandas as pd

            factors = pd.DataFrame(
                columns=["stock_code", "trade_date", "factor_name", "factor_value", "as_of_date"]
            )

        written_rows = write_factor_values(
            connection,
            factors,
            source_run_id=source_run_id,
            replace=replace,
        )

        typer.echo(f"Database path: {db_path}")
        typer.echo(f"Date mode: range {start.isoformat()} to {end.isoformat()}")
        typer.echo(f"source_run_id: {source_run_id}")
        typer.echo("universe_size_by_date:")
        if universe_sizes:
            for trading_date, universe_size in universe_sizes.items():
                typer.echo(f"  {trading_date}: {universe_size}")
        else:
            typer.echo("  (no open trading dates)")
        typer.echo(f"written_rows: {written_rows}")
        _print_factor_counts(_factor_row_counts(factors))
    finally:
        connection.close()


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
