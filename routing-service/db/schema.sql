-- Delta Router Schema
-- Tables for query logging, routing decisions, cost tracking, and metadata caching
CREATE TABLE IF NOT EXISTS query_logs (
    id              SERIAL PRIMARY KEY,
    correlation_id  UUID UNIQUE NOT NULL,
    user_id         VARCHAR(255),
    query_text      TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS routing_decisions (
    id                          SERIAL PRIMARY KEY,
    query_log_id                INTEGER NOT NULL REFERENCES query_logs(id),
    engine                      VARCHAR(20) NOT NULL,
    reason                      TEXT,
    complexity_score            FLOAT,
    estimated_data_bytes        BIGINT,
    has_governance_constraints   BOOLEAN NOT NULL DEFAULT FALSE,
    decided_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS cost_metrics (
    id                  SERIAL PRIMARY KEY,
    query_log_id        INTEGER NOT NULL REFERENCES query_logs(id),
    engine              VARCHAR(20) NOT NULL,
    execution_time_ms   INTEGER,
    estimated_cost_usd  NUMERIC(10, 6),
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS table_metadata_cache (
    table_name          VARCHAR(255) PRIMARY KEY,
    catalog             VARCHAR(255),
    schema_name         VARCHAR(255),
    row_count           BIGINT,
    size_bytes          BIGINT,
    has_rls             BOOLEAN NOT NULL DEFAULT FALSE,
    has_column_masking  BOOLEAN NOT NULL DEFAULT FALSE,
    cached_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds         INTEGER NOT NULL DEFAULT 300
);
CREATE TABLE IF NOT EXISTS collections (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    routing_mode    TEXT NOT NULL CHECK (routing_mode IN ('duckdb', 'databricks', 'smart')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS collection_queries (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    sequence        INTEGER NOT NULL,
    sql_text        TEXT NOT NULL,
    UNIQUE (collection_id, sequence)
);
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_query_logs_submitted_at ON query_logs(submitted_at);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_query_log_id ON routing_decisions(query_log_id);
CREATE INDEX IF NOT EXISTS idx_cost_metrics_query_log_id ON cost_metrics(query_log_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_correlation_id ON query_logs(correlation_id);
CREATE INDEX IF NOT EXISTS idx_collection_queries_collection_id ON collection_queries(collection_id);