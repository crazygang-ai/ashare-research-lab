"""Command-line interface for ashare-research-lab."""

from datetime import datetime
from pathlib import Path
from numbers import Integral
from typing import Any

import duckdb
import click
import typer

from ashare.backtest.config import load_backtest_config, merge_backtest_config
from ashare.backtest.engine import run_topn_equal_weight_backtest
from ashare.factors.calculator import (
    SUPPORTED_FACTORS,
    calculate_factors_for_date,
    open_trading_dates_between,
)
from ashare.factors.config import load_factor_config
from ashare.factors.store import write_factor_values
from ashare.fixtures.builder import build_fixtures as build_fixture_csvs
from ashare.ingest.akshare_provider import AkShareProvider
from ashare.ingest.announcements import ingest_announcements as ingest_announcement_csvs
from ashare.ingest.csv_fallback import CsvFallbackProvider
from ashare.ingest.local import ingest_local as ingest_local_csvs
from ashare.ingest.real_pilot import ingest_real_pilot
from ashare.llm.parser import parse_announcements as parse_announcement_rows
from ashare.pit.asof import AsOfSnapshot, load_as_of_snapshot, parse_as_of_date
from ashare.reports.backtest_report import write_backtest_report
from ashare.reports.candidate_report import write_candidate_report
from ashare.reports.factor_report import write_factor_validation_report
from ashare.scan.candidates import HARD_FILTER_NAMES, scan_candidates
from ashare.storage.db import default_schema_path, init_db
from ashare.validation.config import load_validation_config, merge_validation_config
from ashare.validation.runner import load_data_dictionary, validate_factors as run_factor_validation

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


def _parse_horizon_option(value: str | None) -> list[int] | None:
    if value is None:
        return None
    horizons: list[int] = []
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        try:
            horizon = int(stripped)
        except ValueError as exc:
            raise click.ClickException("--horizon must be a comma-separated integer list.") from exc
        if horizon <= 0:
            raise click.ClickException("--horizon values must be positive integers.")
        horizons.append(horizon)
    if not horizons:
        raise click.ClickException("--horizon must include at least one positive integer.")
    return horizons


def _generated_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _format_float(value: object) -> str:
    if isinstance(value, Integral):
        return str(value)
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    if numeric != numeric:
        return "NaN"
    return f"{numeric:.6f}"


def _print_frame(title: str, frame: Any, verbose: bool = False, limit: int = 10) -> None:
    typer.echo(f"{title}:")
    if frame.empty:
        typer.echo("  (empty)")
        return
    shown = frame if verbose else frame.head(limit)
    text = shown.to_string(index=False, formatters={col: _format_float for col in shown.columns})
    for line in text.splitlines():
        typer.echo(f"  {line}")
    if not verbose and len(frame) > limit:
        typer.echo(f"  ... {len(frame) - limit} more rows")


def _candidate_factor_names(candidates: Any) -> list[str]:
    return [
        str(column).removeprefix("factor__")
        for column in candidates.columns
        if str(column).startswith("factor__")
    ]


def _factor_direction(data_dictionary: dict[str, object], factor_name: str) -> str:
    factors = data_dictionary.get("factors")
    if not isinstance(factors, dict):
        raise click.ClickException("data_dictionary.factors must be a mapping.")
    entry = factors.get(factor_name)
    if not isinstance(entry, dict):
        raise click.ClickException(f"Unknown factor name: {factor_name}")
    direction = entry.get("direction")
    if not isinstance(direction, str):
        raise click.ClickException(f"Missing direction for factor: {factor_name}")
    return direction


@app.command(name="ingest")
def ingest(
    source: str = typer.Option("akshare", "--source"),
    source_tag: str | None = typer.Option(None, "--source-tag"),
    universe: str = typer.Option("hs300", "--universe"),
    index_code: str | None = typer.Option(None, "--index-code"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    universe_as_of: str | None = typer.Option(None, "--universe-as-of"),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    cache_dir: Path = typer.Option(Path("data/raw/cache"), "--cache-dir"),
    cache_mode: str = typer.Option("use", "--cache-mode"),
    fallback_csv_dir: Path | None = typer.Option(None, "--fallback-csv-dir"),
    allow_fallback: bool = typer.Option(False, "--allow-fallback/--no-allow-fallback"),
    max_symbols: int | None = typer.Option(None, "--max-symbols"),
    quality_report_dir: Path = typer.Option(
        Path("data/reports/generated/phase1a7/data-quality"),
        "--quality-report-dir",
    ),
    overwrite_report: bool = typer.Option(False, "--overwrite-report"),
) -> None:
    """Run the Phase 1a-7 real data ingest pilot."""
    warnings: list[str] = []
    resolved_source = source.lower()
    if resolved_source not in {"akshare", "csv", "auto"}:
        raise click.ClickException("--source must be one of: akshare, csv, auto.")
    if cache_mode not in {"use", "refresh", "offline"}:
        raise click.ClickException("--cache-mode must be one of: use, refresh, offline.")
    if universe != "hs300":
        raise click.ClickException("Phase 1a-7 only supports --universe hs300.")
    resolved_index_code = index_code or "000300.SH"
    resolved_universe_as_of = universe_as_of or from_

    if resolved_source == "auto" and not allow_fallback:
        warning = "--source auto without --allow-fallback is equivalent to --source akshare."
        warnings.append(warning)
        typer.echo(f"WARNING: {warning}")

    try:
        if resolved_source == "csv":
            if fallback_csv_dir is None:
                raise click.ClickException("--source csv requires --fallback-csv-dir.")
            provider = CsvFallbackProvider(fallback_csv_dir)
            fallback_provider = None
        else:
            provider = AkShareProvider()
            fallback_provider = (
                CsvFallbackProvider(fallback_csv_dir)
                if allow_fallback and fallback_csv_dir is not None
                else None
            )
            if allow_fallback and fallback_csv_dir is None:
                raise click.ClickException("--allow-fallback requires --fallback-csv-dir.")

        result = ingest_real_pilot(
            db_path=db_path,
            provider=provider,
            universe=universe,
            index_code=resolved_index_code,
            start_date=from_,
            end_date=to,
            universe_as_of_date=resolved_universe_as_of,
            cache_dir=cache_dir,
            cache_mode=cache_mode,
            fallback_provider=fallback_provider,
            allow_fallback=allow_fallback,
            max_symbols=max_symbols,
            quality_report_dir=quality_report_dir,
            source_tag=source_tag,
            overwrite_report=overwrite_report,
            extra_warnings=warnings,
            requested_source=resolved_source,
        )
    except click.ClickException:
        raise
    except (OSError, RuntimeError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    typer.echo("Phase 1a-7 ingest completed.")
    typer.echo(f"Database path: {result.db_path}")
    typer.echo(f"source: {result.source}")
    typer.echo(f"effective_source: {result.effective_source}")
    typer.echo(f"source_tag: {result.source_tag}")
    typer.echo(f"universe: {universe}")
    typer.echo(f"index_code: {resolved_index_code}")
    typer.echo(f"date_range: {from_} to {to}")
    typer.echo(f"universe_as_of_date: {resolved_universe_as_of}")
    typer.echo("row_counts:")
    for dataset, row_count in result.row_counts.items():
        typer.echo(f"  {dataset}: {row_count}")
    typer.echo("cache:")
    typer.echo(f"  hit: {result.cache_counts.get('hit', 0)}")
    typer.echo(f"  miss: {result.cache_counts.get('miss', 0)}")
    typer.echo("quality_report_paths:")
    for name, path in result.quality_report_paths.items():
        typer.echo(f"  {name}: {path}")
    if result.warnings:
        typer.echo("warnings:")
        for warning in result.warnings:
            typer.echo(f"  WARNING: {warning}")


@app.command(name="ingest-announcements")
def ingest_announcements(
    source: str = typer.Option("csv", "--source"),
    source_tag: str | None = typer.Option(None, "--source-tag"),
    input_csv: Path = typer.Option(..., "--input-csv"),
    body_dir: Path | None = typer.Option(None, "--body-dir"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    raw_output_dir: Path = typer.Option(Path("data/raw/announcements"), "--raw-output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite"),
    allow_missing_body: bool = typer.Option(
        False,
        "--allow-missing-body/--no-allow-missing-body",
    ),
) -> None:
    """Ingest Phase 2 CSV announcements and normalized body text."""
    resolved_source = source.lower()
    resolved_source_tag = source_tag or resolved_source
    try:
        result = ingest_announcement_csvs(
            db_path=db_path,
            source=resolved_source,
            source_tag=resolved_source_tag,
            input_csv=input_csv,
            body_dir=body_dir,
            start_date=from_,
            end_date=to,
            raw_output_dir=raw_output_dir,
            overwrite=overwrite,
            allow_missing_body=allow_missing_body,
        )
    except (OSError, RuntimeError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    typer.echo("Announcement ingest completed.")
    typer.echo(f"Database path: {result.db_path}")
    typer.echo(f"source: {result.source}")
    typer.echo(f"source_tag: {result.source_tag}")
    typer.echo(f"date_filter: publish_time {from_} to {to}")
    typer.echo(f"input_rows: {result.input_rows}")
    typer.echo(f"filtered_rows: {result.filtered_rows}")
    typer.echo(f"inserted_rows: {result.inserted_rows}")
    typer.echo(f"skipped_rows: {result.skipped_rows}")
    typer.echo(f"overwritten_rows: {result.overwritten_rows}")


@app.command(name="parse-announcements")
def parse_announcements(
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    as_of: str | None = typer.Option(None, "--as-of"),
    source_tag: str | None = typer.Option(None, "--source-tag"),
    parse_run_id: str = typer.Option(..., "--parse-run-id"),
    llm_mode: str = typer.Option("fixture", "--llm-mode"),
    fixture_response_dir: Path | None = typer.Option(None, "--fixture-response-dir"),
    fixture_variant: str | None = typer.Option(None, "--fixture-variant"),
    model: str = typer.Option("fixture-llm", "--model"),
    limit: int | None = typer.Option(None, "--limit"),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite"),
) -> None:
    """Parse PIT-visible Phase 2 announcements with a fixture or optional LLM client."""
    try:
        result = parse_announcement_rows(
            db_path=db_path,
            start_date=from_,
            end_date=to,
            as_of=as_of,
            source_tag=source_tag,
            parse_run_id=parse_run_id,
            llm_mode=llm_mode,
            fixture_response_dir=fixture_response_dir,
            fixture_variant=fixture_variant,
            model=model,
            limit=limit,
            overwrite=overwrite,
        )
    except (OSError, RuntimeError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    typer.echo("Announcement parse completed.")
    typer.echo(f"Database path: {result.db_path}")
    typer.echo(f"date_filter: effective_date {from_} to {to}")
    if as_of is not None:
        typer.echo(f"as_of: {as_of}")
    if source_tag is not None:
        typer.echo(f"source_tag: {source_tag}")
    typer.echo(f"parse_run_id: {result.parse_run_id}")
    typer.echo(f"llm_mode: {result.llm_mode}")
    typer.echo(f"model: {result.model_name}")
    typer.echo(f"announcement_count: {result.announcement_count}")
    typer.echo(f"success_count: {result.success_count}")
    typer.echo(f"failed_count: {result.failed_count}")
    typer.echo(f"input_tokens: {result.input_tokens}")
    typer.echo(f"output_tokens: {result.output_tokens}")


@app.command(name="validate-factors")
def validate_factors(
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    factor: list[str] | None = typer.Option(None, "--factor"),
    horizon: str | None = typer.Option(None, "--horizon"),
    n_groups: int | None = typer.Option(None, "--n-groups"),
    validation_config: Path = typer.Option(Path("configs/validation.yaml"), "--validation-config"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    include_hard_filters: bool = typer.Option(False, "--include-hard-filters"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Validate stored factor_values against future-return labels."""
    try:
        horizon_override = _parse_horizon_option(horizon)
        loaded_config = load_validation_config(validation_config)
        merged_config = merge_validation_config(
            loaded_config,
            horizons=horizon_override,
            n_groups=n_groups,
        )
        loaded_dictionary = load_data_dictionary(data_dictionary)
        connection = duckdb.connect(str(db_path), read_only=True)
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        try:
            result = run_factor_validation(
                connection=connection,
                start_date=from_,
                end_date=to,
                source_run_id=source_run_id,
                factor_names=factor,
                include_hard_filters=include_hard_filters,
                validation_config=merged_config,
                data_dictionary=loaded_dictionary,
            )
        except (TypeError, ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        connection.close()

    if result.coverage.empty:
        raise click.ClickException(
            "No valid factor input rows found for the requested source_run_id, "
            "date range, factor names, and as_of_date = trade_date filter."
        )

    horizons = ", ".join(str(value) for value in merged_config["horizons"])  # type: ignore[index]
    factors = ", ".join(result.coverage["factor_name"].drop_duplicates().tolist())
    typer.echo(f"Database path: {db_path}")
    typer.echo(f"Validation interval: {from_} to {to}")
    typer.echo(f"source_run_id: {source_run_id}")
    typer.echo(f"factors: {factors}")
    typer.echo(f"horizons: {horizons}")
    typer.echo(f"n_groups: {merged_config['n_groups']}")
    typer.echo(
        "long_short_return is for factor analysis only and is not an executable strategy."
    )

    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}")

    _print_frame("label_summary", result.label_summary, verbose=verbose)

    coverage_summary = (
        result.coverage.groupby("factor_name", as_index=False)
        .agg(
            signal_dates=("trade_date", "nunique"),
            mean_coverage=("coverage", "mean"),
            mean_missing_rate=("missing_rate", "mean"),
        )
        .sort_values("factor_name")
    )
    _print_frame("coverage_summary", coverage_summary, verbose=verbose)
    if verbose:
        _print_frame("coverage_detail", result.coverage, verbose=True)

    _print_frame("ic_summary", result.ic_summary, verbose=verbose)

    if result.group_returns.empty:
        group_summary = result.group_returns
    else:
        group_summary = (
            result.group_returns.groupby(["factor_name", "horizon"], as_index=False)
            .agg(
                valid_group_dates=("trade_date", "nunique"),
                mean_top_return=("top_return", "mean"),
                mean_bottom_return=("bottom_return", "mean"),
                mean_top_minus_bottom_return=("top_minus_bottom_return", "mean"),
                mean_long_short_return=("long_short_return", "mean"),
            )
            .sort_values(["factor_name", "horizon"])
        )
    _print_frame("group_return_summary", group_summary, verbose=verbose)

    _print_frame("decay_curve", result.decay_curve, verbose=verbose)


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
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    as_of: str = typer.Option(..., "--as-of"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    sort_factor: str = typer.Option(..., "--sort-factor"),
    factor: list[str] | None = typer.Option(None, "--factor"),
    top: int = typer.Option(20, "--top"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    output_dir: Path = typer.Option(Path("data/reports/generated/scan"), "--output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Generate a minimal research candidate list from stored factor_values."""
    try:
        parsed_as_of = parse_as_of_date(as_of)
        loaded_dictionary = load_data_dictionary(data_dictionary)
        connection = duckdb.connect(str(db_path), read_only=True)
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        try:
            result = scan_candidates(
                connection=connection,
                as_of_date=parsed_as_of,
                source_run_id=source_run_id,
                sort_factor=sort_factor,
                factor_names=factor,
                top_n=top,
                data_dictionary=loaded_dictionary,
            )
        except (TypeError, ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        connection.close()

    factor_names = _candidate_factor_names(result.candidates)
    metadata = {
        "generated_at": _generated_at(),
        "db_path": str(db_path),
        "source_run_id": source_run_id,
        "as_of_date": parsed_as_of.isoformat(),
        "sort_factor": sort_factor,
        "sort_factor_direction": _factor_direction(loaded_dictionary, sort_factor),
        "top_n": top,
        "factor_names": factor_names,
        "hard_filter_names": HARD_FILTER_NAMES,
        "data_dictionary_path": str(data_dictionary),
    }
    try:
        paths = write_candidate_report(
            result=result,
            output_dir=output_dir,
            metadata=metadata,
            overwrite=overwrite,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}")
    typer.echo("candidate list is for research only and is not a trading instruction.")
    typer.echo(f"Database path: {db_path}")
    typer.echo(f"as_of_date: {parsed_as_of.isoformat()}")
    typer.echo(f"source_run_id: {source_run_id}")
    typer.echo(f"sort_factor: {sort_factor}")
    typer.echo(f"top_n: {top}")
    _print_frame("candidates", result.candidates, verbose=False, limit=top)
    for key, path in paths.items():
        typer.echo(f"{key}: {path}")


@app.command(name="backtest")
def backtest(
    strategy: str = typer.Option(..., "--strategy"),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    sort_factor: str = typer.Option(..., "--sort-factor"),
    index_code: str = typer.Option(..., "--index-code"),
    top: int | None = typer.Option(None, "--top"),
    initial_cash: float | None = typer.Option(None, "--initial-cash"),
    backtest_config: Path = typer.Option(Path("configs/backtest.yaml"), "--backtest-config"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    output_dir: Path = typer.Option(
        Path("data/reports/generated/phase1b/backtest"),
        "--output-dir",
    ),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Run the Phase 1b Top N equal-weight portfolio backtest."""
    if strategy != "topn-equal":
        raise click.ClickException("Phase 1b only supports --strategy topn-equal.")

    try:
        loaded_config = load_backtest_config(backtest_config)
        merged_config = merge_backtest_config(
            loaded_config,
            top_n=top,
            initial_cash=initial_cash,
        )
        loaded_dictionary = load_data_dictionary(data_dictionary)
        portfolio_config = merged_config["portfolio"]
        if not isinstance(portfolio_config, dict):
            raise click.ClickException("backtest config portfolio section must be a mapping.")
        resolved_top = int(portfolio_config["top_n"])
        resolved_initial_cash = float(portfolio_config["initial_cash"])
        connection = duckdb.connect(str(db_path), read_only=True)
    except click.ClickException:
        raise
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        try:
            result = run_topn_equal_weight_backtest(
                connection=connection,
                start_date=from_,
                end_date=to,
                source_run_id=source_run_id,
                sort_factor=sort_factor,
                index_code=index_code,
                top_n=resolved_top,
                initial_cash=resolved_initial_cash,
                backtest_config=merged_config,
                data_dictionary=loaded_dictionary,
            )
        except (TypeError, ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        connection.close()

    metadata = {
        "generated_at": _generated_at(),
        "db_path": str(db_path),
        "start_date": from_,
        "end_date": to,
        "source_run_id": source_run_id,
        "sort_factor": sort_factor,
        "index_code": index_code,
        "top_n": resolved_top,
        "initial_cash": resolved_initial_cash,
        "backtest_config_path": str(backtest_config),
        "data_dictionary_path": str(data_dictionary),
    }
    try:
        paths = write_backtest_report(
            result=result,
            output_dir=output_dir,
            metadata=metadata,
            overwrite=overwrite,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    typer.echo("backtest report is for research only and is not a trading instruction.")
    typer.echo("回测报告仅供研究复盘，不是交易指令。")
    typer.echo(f"Database path: {db_path}")
    typer.echo(f"Backtest interval: {from_} to {to}")
    typer.echo(f"source_run_id: {source_run_id}")
    typer.echo(f"index_code: {index_code}")
    typer.echo(f"sort_factor: {sort_factor}")
    typer.echo(f"top_n: {resolved_top}")
    metrics = result.metrics.iloc[0].to_dict() if not result.metrics.empty else {}
    for name in [
        "total_return",
        "net_return",
        "gross_return",
        "cost_drag",
        "max_drawdown",
        "benchmark_cap_weight_return",
        "benchmark_equal_weight_return",
    ]:
        if name in metrics:
            typer.echo(f"{name}: {_format_float(metrics[name])}")
    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}")
    for key, path in paths.items():
        typer.echo(f"{key}: {path}")


@app.command(name="report")
def report(
    kind: str = typer.Option(..., "--kind", help="Only supported kind: factor-validation."),
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    factor: list[str] | None = typer.Option(None, "--factor"),
    horizon: str | None = typer.Option(None, "--horizon"),
    n_groups: int | None = typer.Option(None, "--n-groups"),
    validation_config: Path = typer.Option(Path("configs/validation.yaml"), "--validation-config"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    include_hard_filters: bool = typer.Option(False, "--include-hard-filters"),
    output_dir: Path = typer.Option(
        Path("data/reports/generated/factor-validation"),
        "--output-dir",
    ),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Generate Phase 1a-6 reports."""
    if kind != "factor-validation":
        raise click.ClickException("Phase 1a-6 only supports --kind factor-validation.")

    try:
        horizon_override = _parse_horizon_option(horizon)
        loaded_config = load_validation_config(validation_config)
        merged_config = merge_validation_config(
            loaded_config,
            horizons=horizon_override,
            n_groups=n_groups,
        )
        loaded_dictionary = load_data_dictionary(data_dictionary)
        connection = duckdb.connect(str(db_path), read_only=True)
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        try:
            result = run_factor_validation(
                connection=connection,
                start_date=from_,
                end_date=to,
                source_run_id=source_run_id,
                factor_names=factor,
                include_hard_filters=include_hard_filters,
                validation_config=merged_config,
                data_dictionary=loaded_dictionary,
            )
        except (TypeError, ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
    finally:
        connection.close()

    if result.coverage.empty:
        raise click.ClickException(
            "No valid factor input rows found for the requested source_run_id, "
            "date range, factor names, and as_of_date = trade_date filter."
        )

    factors = list(factor) if factor else sorted(result.coverage["factor_name"].unique().tolist())
    metadata = {
        "generated_at": _generated_at(),
        "db_path": str(db_path),
        "source_run_id": source_run_id,
        "validation_from": from_,
        "validation_to": to,
        "factors": factors,
        "horizons": list(merged_config["horizons"]),  # type: ignore[index]
        "n_groups": merged_config["n_groups"],
        "include_hard_filters": include_hard_filters,
        "validation_config_path": str(validation_config),
        "data_dictionary_path": str(data_dictionary),
    }
    try:
        paths = write_factor_validation_report(
            result=result,
            output_dir=output_dir,
            metadata=metadata,
            overwrite=overwrite,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}")
    typer.echo(f"Database path: {db_path}")
    typer.echo(f"Validation interval: {from_} to {to}")
    typer.echo(f"source_run_id: {source_run_id}")
    typer.echo(f"factors: {', '.join(str(item) for item in factors)}")
    typer.echo(f"horizons: {', '.join(str(item) for item in metadata['horizons'])}")
    typer.echo(
        "long_short_return is for factor analysis only and is not an executable strategy."
    )
    for key, path in paths.items():
        typer.echo(f"{key}: {path}")


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
