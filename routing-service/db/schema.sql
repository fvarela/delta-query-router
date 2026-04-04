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

-- =============================================================================
-- Phase 10: Benchmark Infrastructure
-- =============================================================================
-- Query collections for benchmark runs
CREATE TABLE IF NOT EXISTS collections (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Queries within a collection, ordered by sequence_number
CREATE TABLE IF NOT EXISTS collection_queries (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    query_text      TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    UNIQUE(collection_id, sequence_number)
);
-- Execution engines (DuckDB workers, Databricks warehouses)
CREATE TABLE IF NOT EXISTS engines (
    id              TEXT PRIMARY KEY,
    engine_type     TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}',
    k8s_service_name TEXT,
    cost_tier       INTEGER NOT NULL DEFAULT 5 CHECK (cost_tier >= 1 AND cost_tier <= 10),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Engine fallback ordering
CREATE TABLE IF NOT EXISTS engine_preferences (
    id              SERIAL PRIMARY KEY,
    engine_id       TEXT NOT NULL REFERENCES engines(id) ON DELETE CASCADE,
    preference_order INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(engine_id)
);
-- Benchmark runs
CREATE TABLE IF NOT EXISTS benchmarks (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES collections(id),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'warming_up', 'running', 'complete', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Warm-up probe results per engine per benchmark
CREATE TABLE IF NOT EXISTS benchmark_engine_warmups (
    id              SERIAL PRIMARY KEY,
    benchmark_id    INTEGER NOT NULL REFERENCES benchmarks(id) ON DELETE CASCADE,
    engine_id       TEXT NOT NULL,
    cold_start_time_ms FLOAT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Per-query per-engine benchmark execution results
CREATE TABLE IF NOT EXISTS benchmark_results (
    id              SERIAL PRIMARY KEY,
    benchmark_id    INTEGER NOT NULL REFERENCES benchmarks(id) ON DELETE CASCADE,
    engine_id       TEXT NOT NULL,
    query_id        INTEGER NOT NULL REFERENCES collection_queries(id),
    execution_time_ms FLOAT,
    io_latency_ms   FLOAT,
    error_message   TEXT
);
-- Storage latency probe measurements
CREATE TABLE IF NOT EXISTS storage_latency_probes (
    id              SERIAL PRIMARY KEY,
    storage_location TEXT NOT NULL,
    engine_id       TEXT NOT NULL,
    probe_time_ms   FLOAT NOT NULL,
    bytes_read      BIGINT,
    measured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed with defaults
INSERT INTO routing_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Seed default DuckDB engines
INSERT INTO engines (id, engine_type, display_name, config, k8s_service_name, cost_tier) VALUES
    ('duckdb-1', 'duckdb', 'DuckDB — Small', '{"memory_gb": 1, "cpu_count": 1}', 'duckdb-worker', 3),
    ('duckdb-2', 'duckdb', 'DuckDB — Medium', '{"memory_gb": 2, "cpu_count": 2}', 'duckdb-worker-medium', 4),
    ('duckdb-3', 'duckdb', 'DuckDB — Large', '{"memory_gb": 4, "cpu_count": 4}', 'duckdb-worker-large', 5)
ON CONFLICT DO NOTHING;



-- =============================================================================
-- Phase 13: ML Model Training Pipeline
-- =============================================================================
-- Trained ML models for latency prediction
CREATE TABLE IF NOT EXISTS models (
    id               SERIAL PRIMARY KEY,
    linked_engines   JSONB NOT NULL DEFAULT '[]',
    latency_model    JSONB NOT NULL DEFAULT '{}',
    training_queries INTEGER NOT NULL DEFAULT 0,
    is_active        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Phase 14: TPC-DS Benchmark Data & External Access Management
-- =============================================================================
-- Track system-created TPC-DS catalogs for lifecycle management and progress
CREATE TABLE IF NOT EXISTS tpcds_catalogs (
    id              SERIAL PRIMARY KEY,
    catalog_name    TEXT UNIQUE NOT NULL,
    schema_name     TEXT NOT NULL,
    scale_factor    INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'creating'
                        CHECK (status IN ('creating', 'ready', 'failed', 'deleting')),
    job_run_id      TEXT,              -- Databricks Job run ID for SF10/SF100, NULL for SF1
    error_message   TEXT,              -- error details if status=failed
    tables_created  INTEGER DEFAULT 0, -- progress: how many tables created so far
    total_tables    INTEGER DEFAULT 25,-- total TPC-DS tables to create
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_prefix ON api_keys(key_prefix);
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_query_logs_submitted_at ON query_logs(submitted_at);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_query_log_id ON routing_decisions(query_log_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_correlation_id ON query_logs(correlation_id);

CREATE INDEX IF NOT EXISTS idx_collection_queries_collection_id ON collection_queries(collection_id);
CREATE INDEX IF NOT EXISTS idx_benchmarks_collection_id ON benchmarks(collection_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_results_benchmark_id ON benchmark_results(benchmark_id);
CREATE INDEX IF NOT EXISTS idx_storage_probes_location_engine ON storage_latency_probes(storage_location, engine_id);