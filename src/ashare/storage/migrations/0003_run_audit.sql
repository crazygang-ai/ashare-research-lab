CREATE TABLE IF NOT EXISTS research_runs (
    run_id VARCHAR,
    as_of_date DATE,
    status VARCHAR,
    params JSON,
    config_hash VARCHAR,
    data_snapshot_id VARCHAR,
    git_sha VARCHAR,
    worktree_clean BOOLEAN,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error VARCHAR
);

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id VARCHAR,
    run_id VARCHAR,
    artifact_kind VARCHAR,
    role VARCHAR,
    path VARCHAR,
    media_type VARCHAR,
    sha256 VARCHAR,
    row_count BIGINT,
    size_bytes BIGINT,
    created_at TIMESTAMP,
    metadata_json JSON
);

CREATE TABLE IF NOT EXISTS research_run_inputs (
    input_id VARCHAR,
    run_id VARCHAR,
    input_kind VARCHAR,
    input_ref VARCHAR,
    source_run_id VARCHAR,
    sha256 VARCHAR,
    row_count BIGINT,
    metadata_json JSON,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS announcement_parse_runs (
    parse_run_id VARCHAR,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status VARCHAR,
    llm_mode VARCHAR,
    model_name VARCHAR,
    schema_version VARCHAR,
    prompt_template_hash VARCHAR,
    config_hash VARCHAR,
    announcement_count INTEGER,
    success_count INTEGER,
    failed_count INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    error VARCHAR
);

CREATE TABLE IF NOT EXISTS announcement_llm_results (
    parse_id VARCHAR,
    parse_run_id VARCHAR,
    announcement_id VARCHAR,
    source VARCHAR,
    source_tag VARCHAR,
    stock_code VARCHAR,
    announcement_type VARCHAR,
    schema_version VARCHAR,
    sentiment VARCHAR,
    summary VARCHAR,
    parsed_json JSON,
    raw_response_json JSON,
    prompt_hash VARCHAR,
    confidence DOUBLE,
    confidence_reasons JSON,
    status VARCHAR,
    error VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS announcement_llm_evidence (
    evidence_id VARCHAR,
    parse_id VARCHAR,
    announcement_id VARCHAR,
    item_type VARCHAR,
    item_index INTEGER,
    evidence_text VARCHAR,
    page INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    locator_status VARCHAR,
    created_at TIMESTAMP
);
