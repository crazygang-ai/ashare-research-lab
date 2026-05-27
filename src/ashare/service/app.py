"""FastAPI app factory for the Phase 4 local query service."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from ashare.service.artifacts import ArtifactRegistry
from ashare.service.config import load_service_config
from ashare.service.queries import (
    artifact_csv_payload,
    database_available,
    factor_validation_payload,
    query_stock_factors,
)
from ashare.service.schemas import with_research_flags
from ashare.service.ui import render_index_html
from ashare.service.ui_runs import (
    Hs300DailyRunRequest,
    StockReportRunRequest,
    UIRunAlreadyRunningError,
    create_ui_run,
    execute_ui_run,
    list_ui_runs,
    read_ui_run,
    stream_log_events,
)
from ashare.service.workflows import (
    WorkflowDatabaseConflictError,
    WorkflowDisabledError,
    WorkflowNotFoundError,
    run_workflow,
    workflow_target_db_paths,
)


def create_app(
    config_path: str | Path = "configs/service.yaml",
    overrides: Mapping[str, object] | None = None,
) -> FastAPI:
    config = load_service_config(config_path=config_path, overrides=overrides)
    registry = ArtifactRegistry(config)
    app = FastAPI(title="ashare-research-lab service", version=config.version)
    app.state.service_config = config
    app.state.artifact_registry = registry

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index_html(config, registry))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return with_research_flags({"status": "ok"})

    @app.get("/api/v1/status")
    def status() -> dict[str, Any]:
        return with_research_flags(
            {
                "version": config.version,
                "database": {
                    "db_path": config.repo_relative(config.database_path),
                    "read_only": config.database_read_only,
                    "available": database_available(config),
                },
                "artifacts": {
                    "roots": [config.repo_relative(root) for root in config.artifact_roots],
                    "known_kinds": list(config.known_artifact_kinds),
                    "audit_schema_available": registry.audit_schema_available(),
                    "artifact_index_available": registry.artifact_index_available(),
                },
                "audit_schema_available": registry.audit_schema_available(),
                "artifact_index_available": registry.artifact_index_available(),
                "latest_run_id": registry.latest_run_id(),
                "latest_formal_run_id": registry.latest_run_id(formal=True),
                "scheduler": {
                    "enabled": config.scheduler_enabled,
                    "timezone": config.scheduler_timezone,
                },
                "workflows": {
                    "target_db_paths": workflow_target_db_paths(config),
                },
            }
        )

    @app.get("/api/v1/ui/config")
    def ui_config() -> dict[str, Any]:
        return with_research_flags(
            {
                "api_base_url": "http://127.0.0.1:8008",
                "database": {
                    "db_path": config.repo_relative(config.database_path),
                    "read_only": config.database_read_only,
                    "available": database_available(config),
                },
                "artifact_roots": [config.repo_relative(root) for root in config.artifact_roots],
                "ui_runner": {
                    "enabled": config.ui_runner_enabled,
                    "history_dir": config.repo_relative(config.ui_runner_history_dir),
                    "log_dir": config.repo_relative(config.ui_runner_log_dir),
                    "allowed_commands": list(config.ui_runner_allowed_commands),
                    "require_confirmation": config.ui_runner_require_confirmation,
                },
                "research_notices": [
                    "candidate list is not a trading instruction",
                    "composite score is not a trading instruction",
                    "backtest is a historical simulation, not a performance promise",
                    "stock report is for research review only",
                    "AkShare HS300 members are a current snapshot, not strict historical PIT.",
                ],
            }
        )

    @app.post("/api/v1/ui/runs/stock-report")
    def ui_stock_report_run(payload: StockReportRunRequest) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = create_ui_run(config, task_type="stock-report", params=payload.model_dump())
        except ValueError as exc:
            return _error(422, "invalid_params", str(exc))
        return _json({"run": run.to_dict()})

    @app.post("/api/v1/ui/runs/hs300-daily")
    def ui_hs300_daily_run(payload: Hs300DailyRunRequest) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = create_ui_run(config, task_type="hs300-daily", params=payload.model_dump())
        except ValueError as exc:
            return _error(422, "invalid_params", str(exc))
        return _json({"run": run.to_dict()})

    @app.get("/api/v1/ui/runs")
    def ui_runs(limit: int = Query(50, ge=1)) -> JSONResponse:
        runs = [run.to_dict() for run in list_ui_runs(config, limit=min(limit, 100))]
        return _json({"runs": runs})

    @app.get("/api/v1/ui/runs/{ui_run_id}")
    def ui_run_detail(ui_run_id: str) -> JSONResponse:
        run = read_ui_run(config, ui_run_id)
        if run is None:
            return _error(404, "ui_run_not_found", "UI run not found.")
        return _json({"run": run.to_dict()})

    @app.post("/api/v1/ui/runs/{ui_run_id}/execute")
    def ui_run_execute(ui_run_id: str) -> JSONResponse:
        if not config.ui_runner_enabled:
            return _error(403, "ui_runner_disabled", "UI runner is disabled.")
        try:
            run = execute_ui_run(config, ui_run_id)
        except UIRunAlreadyRunningError as exc:
            return _error(409, "workflow_already_running", str(exc))
        except FileNotFoundError as exc:
            return _error(404, "ui_run_not_found", str(exc))
        return _json({"run": run.to_dict()})

    @app.get("/api/v1/ui/runs/{ui_run_id}/logs/stream")
    def ui_run_log_stream(ui_run_id: str) -> Response:
        run = read_ui_run(config, ui_run_id)
        if run is None:
            return _error(404, "ui_run_not_found", "UI run not found.")
        if not run.log_paths:
            return _error(404, "log_not_found", "No log path has been recorded for this UI run.")

        log_path = (config.repo_root / run.log_paths[0]).resolve()
        log_dir = config.ui_runner_log_dir.resolve()
        if not log_path.is_relative_to(log_dir) or not log_path.is_file():
            return _error(404, "log_not_found", "UI run log not found.")

        def event_source():
            for event in stream_log_events(log_path, status=run.status):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

        return StreamingResponse(event_source(), media_type="text/event-stream")

    @app.get("/api/v1/artifacts")
    def artifacts(kind: str | None = None, limit: int = Query(20, ge=1)) -> JSONResponse:
        if kind is not None and kind not in config.known_artifact_kinds:
            return _error(400, "unknown_artifact_kind", f"Unknown artifact kind: {kind}")
        capped_limit = min(limit, 100)
        records = registry.list_artifacts(kind=kind, limit=capped_limit)
        return _json({"artifacts": [record.to_dict() for record in records]})

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact_detail(artifact_id: str) -> JSONResponse:
        artifact = registry.get(artifact_id)
        if artifact is None:
            return _error(404, "artifact_not_found", "Artifact not found.")
        return _json({"artifact": artifact.to_dict()})

    @app.get("/api/v1/runs")
    def runs(limit: int = Query(50, ge=1)) -> JSONResponse:
        return _json({"runs": registry.list_runs(limit=min(limit, 100))})

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> JSONResponse:
        run = registry.get_run(run_id)
        if run is None:
            return _error(404, "run_not_found", "Run not found.")
        return _json({"run": run})

    @app.get("/api/v1/runs/{run_id}/artifacts")
    def run_artifacts(run_id: str) -> JSONResponse:
        run = registry.get_run(run_id)
        if run is None:
            return _error(404, "run_not_found", "Run not found.")
        return _json({"run_id": run_id, "artifacts": registry.artifacts_for_run(run_id)})

    @app.get("/api/v1/runs/{run_id}/manifest")
    def run_manifest(run_id: str) -> Response:
        manifest = registry.manifest_for_run(run_id)
        if manifest is None:
            return _error(404, "manifest_not_found", "Run manifest not found.")
        return Response(content=manifest, media_type="application/json; charset=utf-8")

    @app.get("/api/v1/scans/latest")
    def latest_scan() -> JSONResponse:
        return _artifact_kind_response("scan", "candidates.csv")

    @app.get("/api/v1/scans/{artifact_id}")
    def scan_by_id(artifact_id: str) -> JSONResponse:
        return _artifact_id_response(artifact_id, "scan", "candidates.csv")

    @app.get("/api/v1/scoring/latest")
    def latest_scoring() -> JSONResponse:
        return _artifact_kind_response("scoring", "scored_candidates.csv")

    @app.get("/api/v1/scoring/{artifact_id}")
    def scoring_by_id(artifact_id: str) -> JSONResponse:
        return _artifact_id_response(artifact_id, "scoring", "scored_candidates.csv")

    @app.get("/api/v1/backtests/latest")
    def latest_backtest() -> JSONResponse:
        return _artifact_kind_response("backtest", "metrics.csv")

    @app.get("/api/v1/backtests/{artifact_id}")
    def backtest_by_id(artifact_id: str) -> JSONResponse:
        return _artifact_id_response(artifact_id, "backtest", "metrics.csv")

    @app.get("/api/v1/reports/daily/latest")
    def latest_daily_report() -> JSONResponse:
        return _artifact_kind_response("daily_report", "daily_candidates.csv")

    @app.get("/api/v1/reports/daily/latest/markdown")
    def latest_daily_report_markdown() -> Response:
        return _latest_report_markdown_response("daily_report")

    @app.get("/api/v1/reports/stocks/latest")
    def latest_stock_report() -> JSONResponse:
        return _artifact_kind_response("stock_report", "stock_factor_values.csv")

    @app.get("/api/v1/reports/stocks/latest/markdown")
    def latest_stock_report_markdown() -> Response:
        return _latest_report_markdown_response("stock_report")

    @app.get("/api/v1/factors/{factor_name}/validation")
    def factor_validation(factor_name: str) -> JSONResponse:
        artifact = registry.latest("factor_validation")
        if artifact is None:
            return _error(404, "artifact_not_found", "No factor validation artifact found.")
        try:
            payload = factor_validation_payload(registry, artifact, factor_name)
        except (OSError, ValueError) as exc:
            return _error(500, "artifact_read_error", str(exc))
        return _json(payload)

    @app.get("/api/v1/stocks/{stock_code}/factors")
    def stock_factors(
        stock_code: str,
        as_of: str | None = None,
        source_run_id: str | None = None,
    ) -> JSONResponse:
        if not as_of or not source_run_id:
            return _error(
                422,
                "missing_required_query_param",
                "as_of and source_run_id query parameters are required.",
            )
        try:
            rows = query_stock_factors(config, stock_code, as_of, source_run_id)
        except FileNotFoundError as exc:
            return _error(404, "database_not_found", str(exc))
        except (OSError, ValueError, RuntimeError) as exc:
            return _error(500, "duckdb_query_error", str(exc))
        return _json(
            {
                "stock_code": stock_code,
                "as_of": as_of,
                "source_run_id": source_run_id,
                "rows": rows,
            }
        )

    @app.get("/api/v1/reports/{artifact_id}/markdown")
    def report_markdown(artifact_id: str) -> Response:
        text = registry.read_markdown(artifact_id)
        if text is None:
            return _error(404, "artifact_not_found", "Markdown report not found.")
        return Response(content=text, media_type="text/markdown; charset=utf-8")

    @app.get("/api/v1/workflows")
    def workflows() -> dict[str, Any]:
        return with_research_flags(
            {
                "workflows": [
                    {
                        "name": name,
                        "enabled": bool(workflow.get("enabled", False))
                        if isinstance(workflow, Mapping)
                        else False,
                        "description": str(workflow.get("description", ""))
                        if isinstance(workflow, Mapping)
                        else "",
                        "target_db_paths": workflow_target_db_paths(config, name).get(name, []),
                    }
                    for name, workflow in sorted(config.workflows.items())
                ]
            }
        )

    @app.post("/api/v1/workflows/{workflow_name}/run")
    def workflow_run(
        workflow_name: str,
        request: Request,
        dry_run: bool = True,
    ) -> JSONResponse:
        security = config.security
        if not bool(security.get("allow_http_workflow_run", False)):
            return _error(403, "workflow_http_disabled", "HTTP workflow runs are disabled.")
        if bool(security.get("require_token_for_workflows", True)):
            header_name = str(security.get("token_header", "X-Ashare-Token"))
            env_var = str(security.get("token_env_var", "ASHARE_SERVICE_TOKEN"))
            header_token = request.headers.get(header_name)
            expected_token = os.environ.get(env_var)
            if not header_token or not expected_token or header_token != expected_token:
                return _error(401, "missing_or_invalid_token", "Missing or invalid workflow token.")
        try:
            result = run_workflow(
                config,
                workflow_name,
                dry_run=dry_run,
                source="http-api",
                allow_disabled_dry_run=False,
            )
        except WorkflowNotFoundError as exc:
            return _error(404, "workflow_not_found", str(exc))
        except WorkflowDisabledError as exc:
            return _error(409, "workflow_disabled", str(exc))
        except WorkflowDatabaseConflictError as exc:
            return _error(409, "workflow_db_conflict", str(exc))
        return _json({"workflow_run": result})

    def _artifact_kind_response(kind: str, filename: str) -> JSONResponse:
        artifact = registry.latest(kind)
        if artifact is None:
            return _error(404, "artifact_not_found", f"No {kind} artifact found.")
        return _artifact_payload_response(artifact, filename)

    def _artifact_id_response(artifact_id: str, kind: str, filename: str) -> JSONResponse:
        artifact = registry.get(artifact_id)
        if artifact is None or artifact.kind != kind:
            return _error(404, "artifact_not_found", "Artifact not found.")
        return _artifact_payload_response(artifact, filename)

    def _artifact_payload_response(artifact: Any, filename: str) -> JSONResponse:
        try:
            payload = artifact_csv_payload(registry, artifact, filename)
        except (OSError, ValueError) as exc:
            return _error(500, "artifact_read_error", str(exc))
        return _json(payload)

    def _latest_report_markdown_response(kind: str) -> Response:
        artifact = registry.latest(kind)
        if artifact is None:
            return _error(404, "artifact_not_found", f"No {kind} artifact found.")
        text = registry.read_markdown(artifact.artifact_id)
        if text is None:
            return _error(404, "artifact_not_found", "Markdown report not found.")
        return Response(content=text, media_type="text/markdown; charset=utf-8")

    return app


def _json(payload: Mapping[str, Any]) -> JSONResponse:
    return JSONResponse(with_research_flags(payload))


def _error(status_code: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=with_research_flags({"error_code": error_code, "message": message}),
    )
