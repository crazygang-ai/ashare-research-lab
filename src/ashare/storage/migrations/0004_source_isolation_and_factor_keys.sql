ALTER TABLE trading_calendar ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS source_tag VARCHAR;
ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS universe_kind VARCHAR;

UPDATE trading_calendar SET source = 'legacy' WHERE source IS NULL;
UPDATE securities SET source = 'legacy' WHERE source IS NULL;
UPDATE daily_prices SET source = 'legacy' WHERE source IS NULL;
UPDATE universe_members SET source_tag = COALESCE(source, 'legacy') WHERE source_tag IS NULL;
UPDATE universe_members SET universe_kind = 'unknown_legacy' WHERE universe_kind IS NULL;

CREATE TABLE IF NOT EXISTS factor_run_universe (
    source_run_id VARCHAR,
    trade_date DATE,
    as_of_date DATE,
    index_code VARCHAR,
    stock_code VARCHAR,
    universe_source VARCHAR,
    source VARCHAR,
    source_tag VARCHAR,
    universe_kind VARCHAR,
    fingerprint VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provider_smoke_checks (
    check_id VARCHAR,
    provider VARCHAR,
    provider_version VARCHAR,
    capability VARCHAR,
    field_mapping_version VARCHAR,
    status VARCHAR,
    error_category VARCHAR,
    message VARCHAR,
    checked_at TIMESTAMP,
    metadata_json JSON
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_factor_values_unique_key
ON factor_values (source_run_id, stock_code, trade_date, as_of_date, factor_name);
