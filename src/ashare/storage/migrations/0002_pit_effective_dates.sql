ALTER TABLE securities ADD COLUMN IF NOT EXISTS delist_publish_time TIMESTAMP;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS delist_effective_date DATE;

ALTER TABLE industry_classifications ADD COLUMN IF NOT EXISTS in_publish_time TIMESTAMP;
ALTER TABLE industry_classifications ADD COLUMN IF NOT EXISTS in_effective_date DATE;
ALTER TABLE industry_classifications ADD COLUMN IF NOT EXISTS out_publish_time TIMESTAMP;
ALTER TABLE industry_classifications ADD COLUMN IF NOT EXISTS out_effective_date DATE;

ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS in_publish_time TIMESTAMP;
ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS in_effective_date DATE;
ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS out_publish_time TIMESTAMP;
ALTER TABLE universe_members ADD COLUMN IF NOT EXISTS out_effective_date DATE;

ALTER TABLE st_status ADD COLUMN IF NOT EXISTS in_publish_time TIMESTAMP;
ALTER TABLE st_status ADD COLUMN IF NOT EXISTS in_effective_date DATE;
ALTER TABLE st_status ADD COLUMN IF NOT EXISTS out_publish_time TIMESTAMP;
ALTER TABLE st_status ADD COLUMN IF NOT EXISTS out_effective_date DATE;

ALTER TABLE fundamental_reports ADD COLUMN IF NOT EXISTS effective_date DATE;
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS source_tag VARCHAR;
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS effective_date DATE;
ALTER TABLE risk_events ADD COLUMN IF NOT EXISTS effective_date DATE;
