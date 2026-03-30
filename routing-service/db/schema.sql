-- Delta Router Schema
-- Tables for query logging, routing decisions, and metadata caching
CREATE TABLE IF NOT EXISTS query_logs (
    id              SERIAL PRIMARY KEY,
    correlation_id  UUID UNIQUE NOT NULL,
    user_id         VARCHAR(255),
    query_text      TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    execution_time_ms FLOAT,
    routing_log_events JSONB
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
CREATE TABLE IF NOT EXISTS table_metadata_cache (
    table_name                  VARCHAR(255) PRIMARY KEY,
    catalog                     VARCHAR(255),
    schema_name                 VARCHAR(255),
    table_type                  VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
    data_source_format          VARCHAR(50),
    storage_location            TEXT,
    row_count                   BIGINT,
    size_bytes                  BIGINT,
    has_rls                     BOOLEAN NOT NULL DEFAULT FALSE,
    has_column_masking          BOOLEAN NOT NULL DEFAULT FALSE,
    external_engine_read_support BOOLEAN NOT NULL DEFAULT FALSE,
    cached_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds                 INTEGER NOT NULL DEFAULT 300
);
CREATE TABLE IF NOT EXISTS routing_defaults (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    routing_mode    VARCHAR(20) NOT NULL DEFAULT 'smart' CHECK (routing_mode IN ('duckdb', 'databricks', 'smart')),
    complexity_threshold    FLOAT NOT NULL DEFAULT 5.0,
    max_table_size_bytes    BIGINT NOT NULL DEFAULT 1073741824,
    check_governance        BOOLEAN NOT NULL DEFAULT TRUE,
    require_api_key         BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Seed with defaults
INSERT INTO routing_defaults (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS api_keys (
    id              SERIAL PRIMARY KEY,
    key_prefix      VARCHAR(8) NOT NULL,
    key_hash        VARCHAR(255) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    user_id         VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ
);
-- Routing rules: system hard rules + user-defined rules
CREATE TABLE IF NOT EXISTS routing_rules (
    id              SERIAL PRIMARY KEY,
    priority        INTEGER NOT NULL,
    condition_type  TEXT NOT NULL,
    condition_value TEXT NOT NULL,
    target_engine   TEXT NOT NULL,
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);
-- Seed system routing rules (hard rules that cannot be deleted, only toggled)
INSERT INTO routing_rules (id, priority, condition_type, condition_value, target_engine, is_system)
VALUES
    (1, 1, 'table_type', 'VIEW', 'databricks', true),
    (2, 2, 'has_governance', 'row_filter', 'databricks', true),
    (3, 3, 'has_governance', 'column_mask', 'databricks', true),
    (4, 4, 'table_type', 'FOREIGN', 'databricks', true),
    (5, 5, 'external_access', 'false', 'databricks', true)
ON CONFLICT DO NOTHING;

-- Routing settings: singleton row for global routing configuration
CREATE TABLE IF NOT EXISTS routing_settings (
    id                       INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    fit_weight               FLOAT NOT NULL DEFAULT 0.5,
    cost_weight              FLOAT NOT NULL DEFAULT 0.5,
    running_bonus_duckdb     FLOAT NOT NULL DEFAULT 0.05,
    running_bonus_databricks FLOAT NOT NULL DEFAULT 0.15,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Seed with defaults
INSERT INTO routing_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix ON api_keys(key_prefix);
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_query_logs_submitted_at ON query_logs(submitted_at);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_query_log_id ON routing_decisions(query_log_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_correlation_id ON query_logs(correlation_id);