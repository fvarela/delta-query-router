-- Migration 002: Add collections and collection_queries tables
-- Collections store named groups of SQL queries with a routing mode
-- Apply: kubectl exec -it postgresql-0 -- psql -U delta -d deltarouter -f /tmp/002_add_collections.sql
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
CREATE INDEX IF NOT EXISTS idx_collection_queries_collection_id ON collection_queries(collection_id);
