CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date DATE,
    is_open BOOLEAN,
    prev_trade_date DATE,
    next_trade_date DATE
);

CREATE TABLE IF NOT EXISTS securities (
    stock_code VARCHAR,
    stock_name VARCHAR,
    exchange VARCHAR,
    list_date DATE,
    delist_date DATE,
    delist_publish_time TIMESTAMP,
    delist_effective_date DATE
);

CREATE TABLE IF NOT EXISTS industry_classifications (
    stock_code VARCHAR,
    industry_standard VARCHAR,
    industry_l1 VARCHAR,
    industry_l2 VARCHAR,
    in_date DATE,
    out_date DATE,
    in_publish_time TIMESTAMP,
    in_effective_date DATE,
    out_publish_time TIMESTAMP,
    out_effective_date DATE,
    version VARCHAR,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS universe_members (
    index_code VARCHAR,
    stock_code VARCHAR,
    in_date DATE,
    out_date DATE,
    in_publish_time TIMESTAMP,
    in_effective_date DATE,
    out_publish_time TIMESTAMP,
    out_effective_date DATE,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS daily_prices (
    stock_code VARCHAR,
    trade_date DATE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    amount DOUBLE,
    adj_factor DOUBLE,
    is_suspended BOOLEAN,
    limit_up DOUBLE,
    limit_down DOUBLE
);

CREATE TABLE IF NOT EXISTS st_status (
    stock_code VARCHAR,
    st_type VARCHAR,
    in_date DATE,
    out_date DATE,
    in_publish_time TIMESTAMP,
    in_effective_date DATE,
    out_publish_time TIMESTAMP,
    out_effective_date DATE,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS fundamental_reports (
    stock_code VARCHAR,
    report_period DATE,
    publish_time TIMESTAMP,
    effective_date DATE,
    revenue DOUBLE,
    net_profit DOUBLE,
    roe DOUBLE,
    gross_margin DOUBLE,
    operating_cashflow DOUBLE,
    debt_ratio DOUBLE,
    goodwill DOUBLE,
    total_equity DOUBLE,
    accounts_receivable DOUBLE,
    inventory DOUBLE,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS valuation_daily (
    stock_code VARCHAR,
    trade_date DATE,
    pe_ttm DOUBLE,
    pb DOUBLE,
    ps DOUBLE,
    dividend_yield DOUBLE,
    total_mv DOUBLE,
    float_mv DOUBLE,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS announcements (
    announcement_id VARCHAR,
    source VARCHAR,
    source_tag VARCHAR,
    stock_code VARCHAR,
    title VARCHAR,
    announcement_type VARCHAR,
    publish_time TIMESTAMP,
    effective_date DATE,
    url VARCHAR,
    raw_path VARCHAR,
    text_hash VARCHAR
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

CREATE TABLE IF NOT EXISTS risk_events (
    event_id VARCHAR,
    stock_code VARCHAR,
    event_type VARCHAR,
    event_date DATE,
    publish_time TIMESTAMP,
    effective_date DATE,
    payload_json JSON,
    source VARCHAR
);

CREATE TABLE IF NOT EXISTS factor_values (
    stock_code VARCHAR,
    trade_date DATE,
    factor_name VARCHAR,
    factor_value DOUBLE,
    as_of_date DATE,
    source_run_id VARCHAR
);

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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER,
    applied_at TIMESTAMP,
    description VARCHAR
);
