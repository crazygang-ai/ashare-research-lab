"""Announcement LLM parsing orchestration for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import yaml

from ashare.announcements.body_store import normalize_announcement_text
from ashare.announcements.rules import load_announcement_whitelist, match_announcement_rule
from ashare.llm.client import FixtureLLMClient, LLMClient, OpenAICompatibleLLMClient
from ashare.llm.prompts import build_extraction_prompt, prompt_hash, prompt_template_hash
from ashare.llm.schemas import CURRENT_EXTRACTION_SCHEMA_VERSION
from ashare.llm.validators import (
    LocatedEvidence,
    calculate_system_confidence,
    invalid_confidence_reasons,
    locate_evidence,
    schema_error_summary,
    validate_extraction_content,
)
from ashare.storage.db import connect, init_db


DEFAULT_LLM_CONFIG_PATH = Path("configs/llm.yaml")


@dataclass(frozen=True)
class AnnouncementParseSummary:
    db_path: Path
    parse_run_id: str
    llm_mode: str
    model_name: str
    announcement_count: int
    success_count: int
    failed_count: int
    input_tokens: int
    output_tokens: int


def parse_announcements(
    *,
    db_path: str | Path,
    start_date: str | date,
    end_date: str | date,
    parse_run_id: str,
    llm_mode: str,
    model: str,
    as_of: str | date | None = None,
    source_tag: str | None = None,
    fixture_response_dir: str | Path | None = None,
    fixture_variant: str | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    config_path: str | Path = DEFAULT_LLM_CONFIG_PATH,
) -> AnnouncementParseSummary:
    """Parse selected announcements and persist raw/result/evidence records."""
    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    if parsed_start > parsed_end:
        raise ValueError("--from must be on or before --to.")
    parsed_as_of = _parse_date(as_of) if as_of is not None else None

    config = load_llm_config(config_path)
    whitelist = load_announcement_whitelist(config_path)
    max_input_chars = int(config.get("max_input_chars", 20_000))
    resolved_model = model or ("fixture-llm" if llm_mode == "fixture" else "")
    client = _build_client(
        llm_mode=llm_mode,
        model=resolved_model,
        fixture_response_dir=fixture_response_dir,
        fixture_variant=fixture_variant,
    )

    init_db(db_path)
    connection = connect(db_path)
    started_at = datetime.now()
    success_count = 0
    failed_count = 0
    input_tokens = 0
    output_tokens = 0
    selected_rows: list[dict[str, Any]] = []
    try:
        if _parse_run_exists(connection, parse_run_id):
            if not overwrite:
                raise ValueError(f"parse_run_id already exists: {parse_run_id}")
            _delete_parse_run(connection, parse_run_id)

        rows = _load_announcements(
            connection=connection,
            start_date=parsed_start,
            end_date=parsed_end,
            as_of=parsed_as_of,
            source_tag=source_tag,
        )
        for row in rows:
            rule_match = match_announcement_rule(
                title=str(row["title"] or ""),
                raw_announcement_type=str(row["announcement_type"] or ""),
                whitelist=whitelist,
            )
            if rule_match.selected and rule_match.announcement_type in set(whitelist):
                row["rule_announcement_type"] = rule_match.announcement_type
                selected_rows.append(row)
        if limit is not None:
            selected_rows = selected_rows[:limit]

        connection.execute("BEGIN TRANSACTION")
        for row in selected_rows:
            result, evidence_rows, row_input_tokens, row_output_tokens = _parse_one_announcement(
                row=row,
                parse_run_id=parse_run_id,
                client=client,
                model=resolved_model,
                whitelist=whitelist,
                max_input_chars=max_input_chars,
            )
            _insert_parse_result(connection, result)
            for evidence in evidence_rows:
                _insert_evidence(connection, evidence)
            input_tokens += row_input_tokens
            output_tokens += row_output_tokens
            if result["status"] == "success":
                success_count += 1
            else:
                failed_count += 1

        _insert_parse_run(
            connection=connection,
            parse_run_id=parse_run_id,
            started_at=started_at,
            finished_at=datetime.now(),
            status="success" if failed_count == 0 else "partial_failed",
            llm_mode=llm_mode,
            model_name=resolved_model,
            prompt_template_hash_value=prompt_template_hash(),
            config_hash_value=config_hash(config),
            announcement_count=len(selected_rows),
            success_count=success_count,
            failed_count=failed_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=None if failed_count == 0 else f"{failed_count} announcement(s) failed",
        )
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise
    finally:
        connection.close()

    return AnnouncementParseSummary(
        db_path=Path(db_path),
        parse_run_id=parse_run_id,
        llm_mode=llm_mode,
        model_name=resolved_model,
        announcement_count=len(selected_rows),
        success_count=success_count,
        failed_count=failed_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def load_llm_config(config_path: str | Path = DEFAULT_LLM_CONFIG_PATH) -> dict[str, object]:
    """Load the Phase 2 LLM YAML config."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"LLM config must be a mapping: {path}")
    return config


def config_hash(config: dict[str, object]) -> str:
    """Hash parsed LLM config with stable JSON encoding."""
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def make_parse_id(parse_run_id: str, source_tag: str, announcement_id: str) -> str:
    """Return the required stable parse_id."""
    return hashlib.sha1(
        f"{parse_run_id}|{source_tag}|{announcement_id}".encode("utf-8")
    ).hexdigest()


def make_evidence_id(
    *,
    parse_id: str,
    item_type: str,
    item_index: int,
    evidence_text: str,
) -> str:
    """Return the required stable evidence_id."""
    return hashlib.sha1(
        f"{parse_id}|{item_type}|{item_index}|{evidence_text}".encode("utf-8")
    ).hexdigest()


def _build_client(
    *,
    llm_mode: str,
    model: str,
    fixture_response_dir: str | Path | None,
    fixture_variant: str | None,
) -> LLMClient:
    if llm_mode == "fixture":
        if fixture_response_dir is None:
            raise ValueError("--fixture-response-dir is required when --llm-mode fixture.")
        return FixtureLLMClient(fixture_response_dir, variant=fixture_variant)
    if llm_mode == "openai-compatible":
        return OpenAICompatibleLLMClient(model=model)
    raise ValueError("--llm-mode must be one of: fixture, openai-compatible.")


def _load_announcements(
    *,
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
    as_of: date | None,
    source_tag: str | None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            announcement_id,
            source,
            source_tag,
            stock_code,
            title,
            announcement_type,
            publish_time,
            effective_date,
            url,
            raw_path,
            text_hash
        FROM announcements
        WHERE effective_date >= ?
          AND effective_date <= ?
    """
    params: list[Any] = [start_date, end_date]
    if as_of is not None:
        sql += " AND CAST(publish_time AS DATE) <= ? AND effective_date <= ?"
        params.extend([as_of, as_of])
    if source_tag is not None:
        sql += " AND source_tag = ?"
        params.append(source_tag)
    sql += " ORDER BY effective_date, publish_time, source_tag, announcement_id"

    rows = connection.execute(sql, params).fetchall()
    columns = [description[0] for description in connection.description]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _parse_one_announcement(
    *,
    row: dict[str, Any],
    parse_run_id: str,
    client: LLMClient,
    model: str,
    whitelist: tuple[str, ...],
    max_input_chars: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], int, int]:
    now = datetime.now()
    announcement_id = str(row["announcement_id"])
    source_tag = str(row["source_tag"] or "")
    rule_type = str(row["rule_announcement_type"])
    parse_id = make_parse_id(parse_run_id, source_tag, announcement_id)
    raw_path = row.get("raw_path")
    if not raw_path or not Path(str(raw_path)).is_file():
        return (
            _result_row(
                parse_id=parse_id,
                parse_run_id=parse_run_id,
                row=row,
                schema_version=None,
                sentiment=None,
                summary=None,
                parsed_json=None,
                raw_response_json=None,
                prompt_hash_value=None,
                confidence=0.0,
                confidence_reasons=invalid_confidence_reasons("missing announcement body"),
                status="missing_body",
                error="raw_path is missing or file does not exist",
                created_at=now,
            ),
            [],
            0,
            0,
        )

    body_text = Path(str(raw_path)).read_text(encoding="utf-8")
    if not normalize_announcement_text(body_text):
        return (
            _result_row(
                parse_id=parse_id,
                parse_run_id=parse_run_id,
                row=row,
                schema_version=None,
                sentiment=None,
                summary=None,
                parsed_json=None,
                raw_response_json=None,
                prompt_hash_value=None,
                confidence=0.0,
                confidence_reasons=invalid_confidence_reasons("empty announcement body"),
                status="missing_body",
                error="announcement body is empty",
                created_at=now,
            ),
            [],
            0,
            0,
        )

    prompt = build_extraction_prompt(
        announcement_id=announcement_id,
        stock_code=str(row["stock_code"]),
        title=str(row["title"] or ""),
        announcement_type=rule_type,
        publish_time=row["publish_time"],
        effective_date=row["effective_date"],
        body_text=body_text,
        max_input_chars=max_input_chars,
    )
    concrete_prompt_hash = prompt_hash(prompt)

    try:
        response = client.complete(announcement_id=announcement_id, prompt=prompt)
        if not response.content.strip():
            raise RuntimeError("LLM response content is empty.")
    except Exception as exc:
        return (
            _result_row(
                parse_id=parse_id,
                parse_run_id=parse_run_id,
                row=row,
                schema_version=None,
                sentiment=None,
                summary=None,
                parsed_json=None,
                raw_response_json={"error": str(exc)},
                prompt_hash_value=concrete_prompt_hash,
                confidence=0.0,
                confidence_reasons=invalid_confidence_reasons("llm_error"),
                status="llm_error",
                error=str(exc),
                created_at=now,
            ),
            [],
            0,
            0,
        )

    try:
        extraction, parsed_json = validate_extraction_content(response.content)
    except Exception as exc:
        error = schema_error_summary(exc)
        return (
            _result_row(
                parse_id=parse_id,
                parse_run_id=parse_run_id,
                row=row,
                schema_version=None,
                sentiment=None,
                summary=None,
                parsed_json=None,
                raw_response_json=response.raw_response,
                prompt_hash_value=concrete_prompt_hash,
                confidence=0.0,
                confidence_reasons=invalid_confidence_reasons(error),
                status="schema_invalid",
                error=error,
                created_at=now,
            ),
            [],
            response.input_tokens,
            response.output_tokens,
        )

    located = locate_evidence(extraction, body_text)
    confidence, confidence_reasons = calculate_system_confidence(
        extraction=extraction,
        body_text=body_text,
        located_evidence=located,
        rule_announcement_type=rule_type,
        whitelist=whitelist,
    )
    evidence_rows = [
        _evidence_row(
            parse_id=parse_id,
            announcement_id=announcement_id,
            located_evidence=item,
            created_at=now,
        )
        for item in located
    ]
    return (
        _result_row(
            parse_id=parse_id,
            parse_run_id=parse_run_id,
            row=row,
            schema_version=extraction.schema_version,
            sentiment=extraction.sentiment,
            summary=extraction.summary,
            parsed_json=extraction.model_dump(mode="json"),
            raw_response_json=response.raw_response,
            prompt_hash_value=concrete_prompt_hash,
            confidence=confidence,
            confidence_reasons=confidence_reasons,
            status="success",
            error=None,
            created_at=now,
        ),
        evidence_rows,
        response.input_tokens,
        response.output_tokens,
    )


def _result_row(
    *,
    parse_id: str,
    parse_run_id: str,
    row: dict[str, Any],
    schema_version: str | None,
    sentiment: str | None,
    summary: str | None,
    parsed_json: dict[str, Any] | None,
    raw_response_json: dict[str, Any] | None,
    prompt_hash_value: str | None,
    confidence: float,
    confidence_reasons: dict[str, Any],
    status: str,
    error: str | None,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "parse_id": parse_id,
        "parse_run_id": parse_run_id,
        "announcement_id": row["announcement_id"],
        "source": row["source"],
        "source_tag": row["source_tag"],
        "stock_code": row["stock_code"],
        "announcement_type": row["announcement_type"],
        "schema_version": schema_version,
        "sentiment": sentiment,
        "summary": summary,
        "parsed_json": parsed_json,
        "raw_response_json": raw_response_json,
        "prompt_hash": prompt_hash_value,
        "confidence": confidence,
        "confidence_reasons": confidence_reasons,
        "status": status,
        "error": error,
        "created_at": created_at,
    }


def _evidence_row(
    *,
    parse_id: str,
    announcement_id: str,
    located_evidence: LocatedEvidence,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "evidence_id": make_evidence_id(
            parse_id=parse_id,
            item_type=located_evidence.item_type,
            item_index=located_evidence.item_index,
            evidence_text=located_evidence.evidence_text,
        ),
        "parse_id": parse_id,
        "announcement_id": announcement_id,
        "item_type": located_evidence.item_type,
        "item_index": located_evidence.item_index,
        "evidence_text": located_evidence.evidence_text,
        "page": located_evidence.page,
        "char_start": located_evidence.char_start,
        "char_end": located_evidence.char_end,
        "locator_status": located_evidence.locator_status,
        "created_at": created_at,
    }


def _insert_parse_result(
    connection: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
) -> None:
    columns = (
        "parse_id",
        "parse_run_id",
        "announcement_id",
        "source",
        "source_tag",
        "stock_code",
        "announcement_type",
        "schema_version",
        "sentiment",
        "summary",
        "parsed_json",
        "raw_response_json",
        "prompt_hash",
        "confidence",
        "confidence_reasons",
        "status",
        "error",
        "created_at",
    )
    placeholders = [
        "CAST(? AS JSON)" if column in {"parsed_json", "raw_response_json", "confidence_reasons"}
        else "?"
        for column in columns
    ]
    values = [
        json.dumps(row[column], ensure_ascii=False, sort_keys=True)
        if column in {"parsed_json", "raw_response_json", "confidence_reasons"}
        and row[column] is not None
        else row[column]
        for column in columns
    ]
    connection.execute(
        f"INSERT INTO announcement_llm_results ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)})",
        values,
    )


def _insert_evidence(
    connection: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
) -> None:
    columns = (
        "evidence_id",
        "parse_id",
        "announcement_id",
        "item_type",
        "item_index",
        "evidence_text",
        "page",
        "char_start",
        "char_end",
        "locator_status",
        "created_at",
    )
    connection.execute(
        f"INSERT INTO announcement_llm_evidence ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        [row[column] for column in columns],
    )


def _insert_parse_run(
    *,
    connection: duckdb.DuckDBPyConnection,
    parse_run_id: str,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    llm_mode: str,
    model_name: str,
    prompt_template_hash_value: str,
    config_hash_value: str,
    announcement_count: int,
    success_count: int,
    failed_count: int,
    input_tokens: int,
    output_tokens: int,
    error: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO announcement_parse_runs (
            parse_run_id,
            started_at,
            finished_at,
            status,
            llm_mode,
            model_name,
            schema_version,
            prompt_template_hash,
            config_hash,
            announcement_count,
            success_count,
            failed_count,
            input_tokens,
            output_tokens,
            error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            parse_run_id,
            started_at,
            finished_at,
            status,
            llm_mode,
            model_name,
            CURRENT_EXTRACTION_SCHEMA_VERSION,
            prompt_template_hash_value,
            config_hash_value,
            announcement_count,
            success_count,
            failed_count,
            input_tokens,
            output_tokens,
            error,
        ],
    )


def _parse_run_exists(connection: duckdb.DuckDBPyConnection, parse_run_id: str) -> bool:
    count = connection.execute(
        "SELECT COUNT(*) FROM announcement_parse_runs WHERE parse_run_id = ?",
        [parse_run_id],
    ).fetchone()[0]
    return bool(count)


def _delete_parse_run(connection: duckdb.DuckDBPyConnection, parse_run_id: str) -> None:
    connection.execute(
        """
        DELETE FROM announcement_llm_evidence
        WHERE parse_id IN (
            SELECT parse_id
            FROM announcement_llm_results
            WHERE parse_run_id = ?
        )
        """,
        [parse_run_id],
    )
    connection.execute(
        "DELETE FROM announcement_llm_results WHERE parse_run_id = ?",
        [parse_run_id],
    )
    connection.execute(
        "DELETE FROM announcement_parse_runs WHERE parse_run_id = ?",
        [parse_run_id],
    )


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
