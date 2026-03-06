-- Migration 001: Add correlation_id and user_id to query_logs
-- correlation_id: UUID assigned at routing-service entry, used to trace queries across all backends
-- user_id: identifies who submitted the query
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS correlation_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS user_id VARCHAR(255);
CREATE INDEX IF NOT EXISTS idx_query_logs_correlation_id ON query_logs(correlation_id);