"""Command-line interface for ashare-research-lab."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from numbers import Integral
from typing import Any

import duckdb
import click
import pandas as pd
import typer

from ashare.audit.context import AuditContext, NoopAuditContext, generated_run_id
from ashare.audit.run_store import DuplicateRunError
from ashare.backtest.config import load_backtest_config, merge_backtest_config
from ashare.backtest.engine import run_topn_equal_weight_backtest
from ashare.factors.calculator import (
    SUPPORTED_FACTORS,
    calculate_factors_for_date,
    open_trading_dates_between,
)
from ashare.factors.config import load_factor_config
from ashare.factors.store import write_factor_values
from ashare.factors.store import delete_factor_values_for_source_run
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
from ashare.reports.scoring_report import (
    write_scoring_report,
    write_validation_failure_artifacts,
)
from ashare.scan.candidates import HARD_FILTER_NAMES, scan_candidates
from ashare.scoring.config import (
    enabled_groups,
    enabled_risk_penalty_factors,
    enabled_scoring_factors,
    is_strict_mode,
    load_scoring_config,
)
from ashare.scoring.diagnostics import (
    WEIGHT_SENSITIVITY_COLUMNS,
    YEARLY_STABILITY_COLUMNS,
    run_weight_sensitivity,
    run_yearly_stability,
)
from ashare.scoring.scorer import compute_composite_scores
from ashare.scoring.validation_gate import evaluate_validation_gate, load_validation_artifacts
from ashare.storage.db import default_schema_path, init_db
from ashare.validation.config import load_validation_config, merge_validation_config
from ashare.validation.runner import load_data_dictionary, validate_factors as run_factor_validation

app = typer.Typer(help="A-share research assistant CLI.")


def _begin_audit(
    *,
    command: str,
    artifact_kind: str,
    db_path: Path,
    run_id: str,
    run_mode: str | None,
    overwrite_run: bool,
    audit_config: Path,
    output_dir: Path | None,
    as_of_date: str | None,
    source_run_id: str | None,
    params: dict[str, object],
    config_paths: list[Path] | None = None,
    artifact_input_paths: list[Path] | None = None,
) -> AuditContext | NoopAuditContext:
    try:
        context = AuditContext.maybe(
            command=command,
            artifact_kind=artifact_kind,
            db_path=db_path,
            run_id=run_id,
            run_mode=run_mode,
            overwrite_run=overwrite_run,
            audit_config_path=audit_config,
            output_dir=output_dir,
            as_of_date=as_of_date,
            source_run_id=source_run_id,
            params=params,
            config_paths=config_paths or [],
            artifact_input_paths=artifact_input_paths or [],
        )
        context.begin()
        return context
    except DuplicateRunError as exc:
        raise click.ClickException(str(exc)) from exc
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc


def _fail_audit(context: AuditContext | NoopAuditContext | None, exc: BaseException) -> None:
    if context is None:
        return
    try:
        context.fail(str(exc))
    except Exception as audit_exc:
        typer.echo(f"WARNING: failed to write audit failure manifest: {audit_exc}")
    finally:
        context.close()


def _succeed_audit(context: AuditContext | NoopAuditContext, paths: dict[str, Path] | None = None) -> None:
    if paths:
        context.add_artifacts(paths)
    context.succeed()
    _print_audit_summary(context)
    context.close()


def _print_audit_summary(context: AuditContext | NoopAuditContext) -> None:
    for warning in getattr(context, "warnings", []):
        typer.echo(f"WARNING: {warning}")
    run_id = getattr(context, "run_id", None)
    manifest_path = getattr(context, "manifest_path", None)
    if run_id:
        typer.echo(f"run_id: {run_id}")
    if manifest_path:
        display = (
            context.manifest_display_path
            if isinstance(context, AuditContext)
            else str(manifest_path)
        )
        typer.echo(f"manifest: {display}")


def _resolve_output_dir(output_dir: Path | None, context: AuditContext | NoopAuditContext) -> Path:
    if output_dir is not None:
        return output_dir
    resolved = getattr(context, "output_dir", None)
    if resolved is None:
        raise click.ClickException("output_dir could not be resolved.")
    return Path(resolved)


def _artifact_input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists() or not path.is_dir():
        return []
    return sorted(item for item in path.iterdir() if item.is_file())


def _add_factor_calculation_inputs(
    context: AuditContext | NoopAuditContext,
    *,
    index_code: str | None,
    predicate: str,
) -> None:
    for table_name in [
        "trading_calendar",
        "securities",
        "daily_prices",
        "valuation_daily",
        "st_status",
        "fundamental_reports",
    ]:
        context.add_duckdb_table_input(table_name, predicate=predicate)
    if index_code is not None:
        context.add_duckdb_table_input(
            "universe_members",
            predicate=f"index_code={index_code}; {predicate}",
        )


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


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
) -> None:
    """Parse PIT-visible Phase 2 announcements with a fixture or optional LLM client."""
    context = _begin_audit(
        command="parse-announcements",
        artifact_kind="announcement_parse",
        db_path=db_path,
        run_id=run_id or parse_run_id,
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=as_of or to,
        source_run_id=None,
        params={
            "from": from_,
            "to": to,
            "as_of": as_of,
            "source_tag": source_tag,
            "parse_run_id": parse_run_id,
            "llm_mode": llm_mode,
            "fixture_response_dir": str(fixture_response_dir) if fixture_response_dir else None,
            "fixture_variant": fixture_variant,
            "model": model,
            "limit": limit,
            "overwrite": overwrite,
        },
        config_paths=[Path("configs/llm.yaml")],
        artifact_input_paths=_artifact_input_files(fixture_response_dir)
        if fixture_response_dir is not None
        else [],
    )
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
        context.add_duckdb_table_input(
            "announcements",
            predicate=f"effective_date {from_}..{to}; source_tag={source_tag}",
        )
        context.add_duckdb_table_input(
            "announcement_llm_results",
            predicate=f"parse_run_id={parse_run_id}",
        )
        summary_path = _resolve_output_dir(output_dir, context) / "parse_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "parse_run_id": result.parse_run_id,
                    "llm_mode": result.llm_mode,
                    "model_name": result.model_name,
                    "announcement_count": result.announcement_count,
                    "success_count": result.success_count,
                    "failed_count": result.failed_count,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
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
        _succeed_audit(context, {"summary": summary_path})
    except (OSError, RuntimeError, ValueError, duckdb.Error) as exc:
        _fail_audit(context, exc)
        raise click.ClickException(str(exc)) from exc


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
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
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
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="validate-factors",
        artifact_kind="factor_validation",
        db_path=db_path,
        run_id=run_id or generated_run_id("validate-factors"),
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=to,
        source_run_id=source_run_id,
        params={
            "from": from_,
            "to": to,
            "factor": factor,
            "horizon": horizon,
            "n_groups": n_groups,
            "validation_config": str(validation_config),
            "data_dictionary": str(data_dictionary),
            "include_hard_filters": include_hard_filters,
            "verbose": verbose,
        },
        config_paths=[validation_config, data_dictionary],
    )
    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path), read_only=True)
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
        context.add_duckdb_table_input(
            "factor_values",
            source_run_id=source_run_id,
            predicate=f"source_run_id={source_run_id}; {from_}..{to}",
        )
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        if not isinstance(context, AuditContext):
            connection.close()

    if result.coverage.empty:
        exc = click.ClickException(
            "No valid factor input rows found for the requested source_run_id, "
            "date range, factor names, and as_of_date = trade_date filter."
        )
        _fail_audit(context, exc)
        raise exc

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
    _succeed_audit(context)


@app.command(name="event-study")
def event_study(
    event: str = typer.Option(..., "--event"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    horizon: str = typer.Option("5,20,60", "--horizon"),
) -> None:
    """Print event-study parameters without running an event study."""
    _echo_todo("event-study", event=event, from_=from_, to=to, horizon=horizon)


@app.command(name="serve")
def serve(
    service_config: Path = typer.Option(Path("configs/service.yaml"), "--service-config"),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload/--no-reload"),
    enable_scheduler: bool = typer.Option(False, "--enable-scheduler"),
) -> None:
    """Start the local read-only FastAPI query service."""
    from ashare.service.app import create_app
    from ashare.service.config import load_service_config
    from ashare.service.scheduler import start_embedded_scheduler

    overrides: dict[str, object] = {"server": {"reload": reload}}
    server_overrides: dict[str, object] = {}
    if host is not None:
        server_overrides["host"] = host
    if port is not None:
        server_overrides["port"] = port
    if server_overrides:
        server_overrides["reload"] = reload
        overrides["server"] = server_overrides

    try:
        config = load_service_config(service_config, overrides=overrides)
        fastapi_app = create_app(service_config, overrides=overrides)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if enable_scheduler:
        typer.echo(
            "WARNING: embedded scheduler is for local convenience only; do not run "
            "ashare service-scheduler simultaneously."
        )
        scheduler = start_embedded_scheduler(config)
        if scheduler is None:
            typer.echo("WARNING: scheduler.enabled is false; embedded scheduler has no jobs.")

    typer.echo("service is for research review only and is not a trading system.")
    typer.echo("服务仅用于研究查询，不是交易系统。")
    typer.echo(f"Service URL: http://{config.host}:{config.port}")

    import uvicorn

    uvicorn.run(fastapi_app, host=config.host, port=config.port, reload=config.reload)


@app.command(name="service-workflow")
def service_workflow(
    service_config: Path = typer.Option(Path("configs/service.yaml"), "--service-config"),
    name: str = typer.Option(..., "--name"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute"),
) -> None:
    """Run or dry-run a configured Phase 4 service workflow."""
    from ashare.service.config import load_service_config
    from ashare.service.workflows import (
        WorkflowDatabaseConflictError,
        WorkflowDisabledError,
        WorkflowNotFoundError,
        run_workflow,
    )

    try:
        config = load_service_config(service_config)
        result = run_workflow(
            config,
            name,
            dry_run=dry_run,
            source="service-workflow-cli",
            allow_disabled_dry_run=True,
        )
    except (OSError, ValueError, WorkflowNotFoundError, WorkflowDisabledError, WorkflowDatabaseConflictError) as exc:
        raise click.ClickException(str(exc)) from exc

    typer.echo(f"workflow: {result['workflow_name']}")
    typer.echo(f"source: {result['source']}")
    typer.echo(f"dry_run: {result['dry_run']}")
    typer.echo(f"status: {result['status']}")
    if result.get("target_db_paths"):
        typer.echo("target_db_paths:")
        for target in result["target_db_paths"]:
            typer.echo(f"  {target}")
    for warning in result.get("warnings", []):
        typer.echo(f"WARNING: {warning}")
    typer.echo("steps:")
    for step in result["steps"]:
        typer.echo(f"  - {step['name']}: {' '.join(step['command'])}")
    if result.get("log_path"):
        typer.echo(f"log_path: {result['log_path']}")


@app.command(name="service-scheduler")
def service_scheduler(
    service_config: Path = typer.Option(Path("configs/service.yaml"), "--service-config"),
    once: bool = typer.Option(False, "--once"),
    name: str | None = typer.Option(None, "--name"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute"),
) -> None:
    """Run the local APScheduler entry point for configured workflows."""
    from ashare.service.config import load_service_config
    from ashare.service.scheduler import (
        SchedulerDisabledError,
        run_scheduler_forever,
        run_scheduler_once,
    )
    from ashare.service.workflows import WorkflowError

    try:
        config = load_service_config(service_config)
        if once:
            results = run_scheduler_once(config, name=name, dry_run=dry_run)
            for result in results:
                typer.echo(f"workflow: {result['workflow_name']}")
                typer.echo(f"dry_run: {result['dry_run']}")
                typer.echo(f"status: {result['status']}")
                for warning in result.get("warnings", []):
                    typer.echo(f"WARNING: {warning}")
                for step in result.get("steps", []):
                    typer.echo(f"  - {step['name']}: {' '.join(step['command'])}")
                if result.get("log_path"):
                    typer.echo(f"log_path: {result['log_path']}")
            return
        run_scheduler_forever(config, name=name, dry_run=dry_run)
    except (OSError, ValueError, SchedulerDisabledError, WorkflowError) as exc:
        raise click.ClickException(str(exc)) from exc


@app.command(name="scan")
def scan(
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    as_of: str = typer.Option(..., "--as-of"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    index_code: str | None = typer.Option(None, "--index-code"),
    sort_factor: str = typer.Option(..., "--sort-factor"),
    factor: list[str] | None = typer.Option(None, "--factor"),
    top: int = typer.Option(20, "--top"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
) -> None:
    """Generate a minimal research candidate list from stored factor_values."""
    try:
        parsed_as_of = parse_as_of_date(as_of)
        loaded_dictionary = load_data_dictionary(data_dictionary)
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="scan",
        artifact_kind="scan",
        db_path=db_path,
        run_id=run_id or generated_run_id("scan"),
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=parsed_as_of.isoformat(),
        source_run_id=source_run_id,
        params={
            "as_of": as_of,
            "index_code": index_code,
            "sort_factor": sort_factor,
            "factor": factor,
            "top": top,
            "data_dictionary": str(data_dictionary),
            "overwrite": overwrite,
        },
        config_paths=[data_dictionary],
    )
    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path), read_only=True)
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
        context.add_duckdb_table_input("factor_values", source_run_id=source_run_id)
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        if not isinstance(context, AuditContext):
            connection.close()

    factor_names = _candidate_factor_names(result.candidates)
    metadata = {
        "generated_at": _generated_at(),
        "db_path": str(db_path),
        "source_run_id": source_run_id,
        "index_code": index_code,
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
            output_dir=_resolve_output_dir(output_dir, context),
            metadata=metadata,
            overwrite=overwrite or overwrite_run,
        )
    except (OSError, ValueError) as exc:
        _fail_audit(context, exc)
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
    _succeed_audit(context, paths)


@app.command(name="score")
def score(
    db_path: Path = typer.Option(Path("data/processed/ashare.duckdb"), "--db-path"),
    as_of: str = typer.Option(..., "--as-of"),
    source_run_id: str = typer.Option(..., "--source-run-id"),
    index_code: str = typer.Option(..., "--index-code"),
    validation_dir: Path = typer.Option(..., "--validation-dir"),
    scoring_config: Path = typer.Option(Path("configs/scoring.yaml"), "--scoring-config"),
    data_dictionary: Path = typer.Option(Path("configs/data_dictionary.yaml"), "--data-dictionary"),
    top: int | None = typer.Option(None, "--top"),
    diagnostics_from: str | None = typer.Option(None, "--diagnostics-from"),
    diagnostics_to: str | None = typer.Option(None, "--diagnostics-to"),
    horizon: str | None = typer.Option(None, "--horizon"),
    skip_diagnostics: bool = typer.Option(False, "--skip-diagnostics"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
) -> None:
    """Generate Phase 3 composite scoring reports from validated factor values."""
    if (diagnostics_from is None) ^ (diagnostics_to is None):
        raise click.ClickException(
            "--diagnostics-from and --diagnostics-to must be provided together."
        )
    try:
        parsed_as_of = parse_as_of_date(as_of)
        loaded_config = load_scoring_config(scoring_config)
        loaded_dictionary = load_data_dictionary(data_dictionary)
        artifacts = load_validation_artifacts(validation_dir)
        gate_result = evaluate_validation_gate(
            artifacts=artifacts,
            scoring_config=loaded_config,
            data_dictionary=loaded_dictionary,
        )
        score_section = loaded_config.get("score", {})
        if not isinstance(score_section, dict):
            raise click.ClickException("score config section must be a mapping.")
        resolved_top = int(top if top is not None else score_section.get("top_n", 20))
        horizons = _parse_horizon_option(horizon)
        if horizons is None:
            diagnostics = loaded_config.get("diagnostics", {})
            yearly = diagnostics.get("yearly_stability", {}) if isinstance(diagnostics, dict) else {}
            if not isinstance(yearly, dict):
                yearly = {}
            horizons = [int(value) for value in yearly.get("horizons", [20])]
        metadata: dict[str, object] = {
            "generated_at": _generated_at(),
            "db_path": str(db_path),
            "as_of_date": parsed_as_of.isoformat(),
            "source_run_id": source_run_id,
            "index_code": index_code,
            "scoring_config_path": str(scoring_config),
            "data_dictionary_path": str(data_dictionary),
            "validation_dir": str(validation_dir),
            "config_hash": _file_sha256(scoring_config),
            "top_n": resolved_top,
            "horizons": horizons,
            "diagnostics_from": diagnostics_from,
            "diagnostics_to": diagnostics_to,
            "skip_diagnostics": skip_diagnostics,
            "enabled_groups": list(enabled_groups(loaded_config).keys()),
            "enabled_factors": enabled_scoring_factors(loaded_config),
            "enabled_risk_penalty_factors": enabled_risk_penalty_factors(loaded_config),
            "warnings": [],
        }
    except click.ClickException:
        raise
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="score",
        artifact_kind="scoring",
        db_path=db_path,
        run_id=run_id or generated_run_id("score"),
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=parsed_as_of.isoformat(),
        source_run_id=source_run_id,
        params={
            "as_of": as_of,
            "index_code": index_code,
            "validation_dir": str(validation_dir),
            "scoring_config": str(scoring_config),
            "data_dictionary": str(data_dictionary),
            "top": top,
            "diagnostics_from": diagnostics_from,
            "diagnostics_to": diagnostics_to,
            "horizon": horizon,
            "skip_diagnostics": skip_diagnostics,
            "overwrite": overwrite,
        },
        config_paths=[scoring_config, data_dictionary],
        artifact_input_paths=_artifact_input_files(validation_dir),
    )
    context.add_duckdb_table_input("factor_values", source_run_id=source_run_id)

    gate_failures = gate_result.table[
        (gate_result.table["configured_enabled"].astype(bool))
        & (gate_result.table["validation_status"] != "PASS")
    ]
    if is_strict_mode(loaded_config) and not gate_failures.empty:
        error_summary = gate_failures.loc[:, ["factor_name", "reason"]].to_dict("records")
        metadata["warnings"] = [
            *gate_result.warnings,
            "Validation gate failed in strict mode.",
        ]
        metadata["validation_errors"] = error_summary
        try:
            paths = write_validation_failure_artifacts(
                validation_gate=gate_result.table,
                output_dir=_resolve_output_dir(output_dir, context),
                metadata=metadata,
                overwrite=overwrite or overwrite_run,
            )
        except (OSError, ValueError) as exc:
            _fail_audit(context, exc)
            raise click.ClickException(str(exc)) from exc
        for key, path in paths.items():
            typer.echo(f"{key}: {path}")
        exc = click.ClickException("Validation gate failed in strict mode.")
        context.add_artifacts(paths)
        _fail_audit(context, exc)
        raise exc

    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path), read_only=True)

    try:
        try:
            result = compute_composite_scores(
                connection=connection,
                as_of_date=parsed_as_of,
                source_run_id=source_run_id,
                index_code=index_code,
                scoring_config=loaded_config,
                data_dictionary=loaded_dictionary,
                validation_gate=gate_result,
                top_n=resolved_top,
            )
            run_warnings = list(result.warnings)
            if skip_diagnostics:
                weight_sensitivity = pd.DataFrame(columns=WEIGHT_SENSITIVITY_COLUMNS)
                yearly_stability = pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS)
                run_warnings.append("Diagnostics skipped by --skip-diagnostics.")
            else:
                weight_sensitivity = run_weight_sensitivity(
                    base_result=result,
                    scoring_config=loaded_config,
                    top_n=resolved_top,
                )
                if diagnostics_from is not None and diagnostics_to is not None:
                    yearly_stability = run_yearly_stability(
                        connection=connection,
                        start_date=diagnostics_from,
                        end_date=diagnostics_to,
                        source_run_id=source_run_id,
                        index_code=index_code,
                        scoring_config=loaded_config,
                        data_dictionary=loaded_dictionary,
                        validation_gate=gate_result,
                        horizons=horizons,
                    )
                else:
                    yearly_stability = pd.DataFrame(columns=YEARLY_STABILITY_COLUMNS)
                    run_warnings.append(
                        "No diagnostics date range provided; yearly_stability.csv is empty."
                    )

            metadata["warnings"] = list(dict.fromkeys([*gate_result.warnings, *run_warnings]))
            paths = write_scoring_report(
                result=result,
                output_dir=_resolve_output_dir(output_dir, context),
                metadata=metadata,
                weight_sensitivity=weight_sensitivity,
                yearly_stability=yearly_stability,
                overwrite=overwrite or overwrite_run,
            )
        except (OSError, ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        if not isinstance(context, AuditContext):
            connection.close()

    typer.echo("composite score is for research only and is not a trading instruction.")
    typer.echo("综合评分仅供研究复盘，不是交易指令。")
    typer.echo(f"Database path: {db_path}")
    typer.echo(f"as_of_date: {parsed_as_of.isoformat()}")
    typer.echo(f"source_run_id: {source_run_id}")
    typer.echo(f"index_code: {index_code}")
    typer.echo(f"top_n: {resolved_top}")
    validation_counts = result.validation_gate["validation_status"].value_counts().to_dict()
    typer.echo("validation_gate_summary:")
    for status, count in sorted(validation_counts.items()):
        typer.echo(f"  {status}: {count}")
    for warning in metadata["warnings"]:  # type: ignore[index]
        typer.echo(f"WARNING: {warning}")
    _print_frame("top_candidates", result.scored_candidates, verbose=False, limit=resolved_top)
    for key, path in paths.items():
        typer.echo(f"{key}: {path}")
    _succeed_audit(context, paths)


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
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
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
    except click.ClickException:
        raise
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="backtest",
        artifact_kind="backtest",
        db_path=db_path,
        run_id=run_id or generated_run_id("backtest"),
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=to,
        source_run_id=source_run_id,
        params={
            "strategy": strategy,
            "from": from_,
            "to": to,
            "sort_factor": sort_factor,
            "index_code": index_code,
            "top": top,
            "initial_cash": initial_cash,
            "backtest_config": str(backtest_config),
            "data_dictionary": str(data_dictionary),
            "overwrite": overwrite,
        },
        config_paths=[backtest_config, data_dictionary],
    )
    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path), read_only=True)
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
        context.add_duckdb_table_input("factor_values", source_run_id=source_run_id)
        context.add_duckdb_table_input("daily_prices", predicate=f"{from_}..{to}")
        context.add_duckdb_table_input("universe_members", predicate=f"index_code={index_code}")
        context.add_duckdb_table_input("valuation_daily", predicate=f"{from_}..{to}")
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        if not isinstance(context, AuditContext):
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
            output_dir=_resolve_output_dir(output_dir, context),
            metadata=metadata,
            overwrite=overwrite or overwrite_run,
        )
    except (OSError, ValueError) as exc:
        _fail_audit(context, exc)
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
    _succeed_audit(context, paths)


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
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
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
    except (OSError, ValueError, duckdb.Error) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="report",
        artifact_kind="factor_validation",
        db_path=db_path,
        run_id=run_id or generated_run_id("report"),
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=output_dir,
        as_of_date=to,
        source_run_id=source_run_id,
        params={
            "kind": kind,
            "from": from_,
            "to": to,
            "factor": factor,
            "horizon": horizon,
            "n_groups": n_groups,
            "validation_config": str(validation_config),
            "data_dictionary": str(data_dictionary),
            "include_hard_filters": include_hard_filters,
            "overwrite": overwrite,
        },
        config_paths=[validation_config, data_dictionary],
    )
    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path), read_only=True)
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
        context.add_duckdb_table_input(
            "factor_values",
            source_run_id=source_run_id,
            predicate=f"{from_}..{to}",
        )
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        if not isinstance(context, AuditContext):
            connection.close()

    if result.coverage.empty:
        exc = click.ClickException(
            "No valid factor input rows found for the requested source_run_id, "
            "date range, factor names, and as_of_date = trade_date filter."
        )
        _fail_audit(context, exc)
        raise exc

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
            output_dir=_resolve_output_dir(output_dir, context),
            metadata=metadata,
            overwrite=overwrite or overwrite_run,
        )
    except (OSError, ValueError) as exc:
        _fail_audit(context, exc)
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
    _succeed_audit(context, paths)


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
    run_id: str | None = typer.Option(None, "--run-id"),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    overwrite_run: bool = typer.Option(False, "--overwrite-run/--no-overwrite-run"),
    audit_config: Path = typer.Option(Path("configs/audit.yaml"), "--audit-config"),
    include_delisted: bool = typer.Option(False, "--include-delisted"),
    replace: bool = typer.Option(False, "--replace/--append"),
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
    if replace and not overwrite_run:
        raise click.ClickException("--replace is deprecated for audited runs; use --overwrite-run.")

    resolved_run_id = run_id or source_run_id
    if run_id is not None and run_id != source_run_id:
        raise click.ClickException("--run-id must equal --source-run-id for calculate-factors.")

    try:
        parsed_config = load_factor_config(factor_config)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    context = _begin_audit(
        command="calculate-factors",
        artifact_kind="factor_values",
        db_path=db_path,
        run_id=resolved_run_id,
        run_mode=run_mode,
        overwrite_run=overwrite_run,
        audit_config=audit_config,
        output_dir=None,
        as_of_date=as_of or to,
        source_run_id=source_run_id,
        params={
            "as_of": as_of,
            "from": from_,
            "to": to,
            "index_code": index_code,
            "factor": factor,
            "factor_config": str(factor_config),
            "include_delisted": include_delisted,
        },
        config_paths=[factor_config],
    )
    connection = context.connection if isinstance(context, AuditContext) else duckdb.connect(str(db_path))
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

            try:
                if overwrite_run:
                    deleted_rows = delete_factor_values_for_source_run(connection, source_run_id)
                    typer.echo(f"overwrite_deleted_factor_rows: {deleted_rows}")
                written_rows = write_factor_values(
                    connection,
                    factors,
                    source_run_id=source_run_id,
                    replace=False,
                )
            except (ValueError, duckdb.Error) as exc:
                raise click.ClickException(str(exc)) from exc
            _add_factor_calculation_inputs(
                context,
                index_code=index_code,
                predicate=f"as_of={parsed_as_of.isoformat()}",
            )
            typer.echo(f"Database path: {db_path}")
            typer.echo(f"Date mode: as-of {parsed_as_of.isoformat()}")
            typer.echo(f"source_run_id: {source_run_id}")
            typer.echo(f"universe_size: {factors.attrs.get('universe_size', 0)}")
            typer.echo(f"written_rows: {written_rows}")
            _print_factor_counts(_factor_row_counts(factors))
            _succeed_audit(context)
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

        try:
            if overwrite_run:
                deleted_rows = delete_factor_values_for_source_run(connection, source_run_id)
                typer.echo(f"overwrite_deleted_factor_rows: {deleted_rows}")
            written_rows = write_factor_values(
                connection,
                factors,
                source_run_id=source_run_id,
                replace=False,
            )
        except (ValueError, duckdb.Error) as exc:
            raise click.ClickException(str(exc)) from exc
        _add_factor_calculation_inputs(
            context,
            index_code=index_code,
            predicate=f"{start.isoformat()}..{end.isoformat()}",
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
        _succeed_audit(context)
    except click.ClickException as exc:
        _fail_audit(context, exc)
        raise
    finally:
        context.close()


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
