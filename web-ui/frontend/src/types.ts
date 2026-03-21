// --- Workspace ---
export interface Workspace {
  id: string;
  name: string;
  url: string;
  token: string | null; // PAT — null means not yet entered
  connected: boolean;
}

// --- Databricks settings (kept for mock API compat) ---
export interface DatabricksSettings {
  configured: boolean;
  host?: string;
  username?: string;
  warehouse_id?: string | null;
}

export interface DatabricksCredentials {
  host: string;
  token: string;
}

export interface DatabricksConnectResponse {
  status: string;
  host: string;
  username: string;
}

export interface Warehouse {
  id: string;
  name: string;
  state: string;
}

// --- Collections & Queries ---
export interface Collection {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface CollectionWithQueries extends Collection {
  queries: Query[];
}

export interface Query {
  id: number;
  collection_id: number;
  query_text: string;
  sequence_number: number;
}

// --- Engine catalog ---
export type EngineRuntimeState = "running" | "stopped" | "starting" | "unknown";

export interface EngineCatalogEntry {
  id: number;
  engine_type: "databricks_sql" | "duckdb";
  display_name: string;
  config: Record<string, any>;
  is_default: boolean;
  enabled: boolean;
  runtime_state: EngineRuntimeState;
  created_at: string;
  updated_at: string;
}

export interface EnginePreference {
  engine_id: string;
  display_name: string;
  engine_type: "databricks_sql" | "duckdb";
  preference_order: number;
}

// --- Routing rules ---
export interface RoutingRule {
  id: number;
  priority: number;
  condition_type: string;
  condition_value: string;
  target_engine: string;
  is_system: boolean;
  enabled: boolean;
}

// --- Routing settings ---
export interface RoutingSettings {
  latency_weight: number;
  cost_weight: number;
  cost_estimation_mode: "formula" | "model";
  running_bonus_duckdb: number;
  running_bonus_databricks: number;
}

// --- Run mode ---
export type RunMode = "single" | "multi";

// --- Panel mode (Run vs Train) ---
export type PanelMode = "run" | "train";

// --- Query execution ---
export interface QueryExecutionRequest {
  sql: string;
  routing_mode: "smart" | "duckdb" | "databricks";
}

export interface QueryExecutionResult {
  correlation_id: string;
  routing_decision: {
    engine: string;
    engine_display_name: string;
    stage: "mandatory_rule" | "user_rule" | "ml_prediction" | "fallback";
    reason: string;
    complexity_score: number;
    // Decomposed latency (ODQ-9 / ODQ-10)
    compute_time_ms?: number;
    io_latency_ms?: number;
    cold_start_ms?: number;
    total_latency_ms?: number;
    // Cost and scoring (ODQ-10)
    estimated_cost_usd?: number;
    latency_score?: number;
    cost_score?: number;
    weighted_score?: number;
  };
  execution: {
    execution_time_ms: number;
    data_scanned_bytes: number;
    estimated_cost_usd: number;
    cost_savings_usd: number;
  };
  columns: string[];
  rows: any[][];
}

// --- Benchmarks ---
export interface BenchmarkSummary {
  id: number;
  collection_id: number;
  status: "provisioning" | "warming_up" | "running" | "cleaning_up" | "complete" | "failed";
  engine_count: number;
  created_at: string;
  updated_at: string;
}

export interface BenchmarkDetail extends BenchmarkSummary {
  warmups: BenchmarkWarmup[];
  results: BenchmarkResult[];
  storage_probes?: StorageLatencyProbe[];
}

export interface BenchmarkWarmup {
  engine_id: string;
  engine_display_name: string;
  cold_start_time_ms: number;
  started_at: string;
}

export interface BenchmarkResult {
  engine_id: string;
  engine_display_name: string;
  query_id: number;
  execution_time_ms: number;
  data_scanned_bytes: number;
  io_latency_ms?: number; // ODQ-9: I/O latency component
}

// --- ML Models (bundle: latency + cost trained together) ---
export interface SubModelMetrics {
  r_squared: number;
  mae_ms?: number;  // latency model: MAE in milliseconds
  mae_usd?: number; // cost model: MAE in USD
  model_path: string;
}

export interface Model {
  id: number;
  linked_engines: string[];
  latency_model: SubModelMetrics;
  cost_model: SubModelMetrics;
  is_active: boolean;
  created_at: string;
  benchmark_count?: number;
  training_queries?: number; // total queries used in training
}

// --- Storage Latency Probes (ODQ-9) ---
export interface StorageLatencyProbe {
  id: number;
  storage_location: string;
  engine_id: string;
  engine_display_name: string;
  probe_time_ms: number;
  bytes_read: number;
  measured_at: string;
}

// --- Unity Catalog ---
export interface CatalogInfo {
  name: string;
}

export interface SchemaInfo {
  name: string;
  catalog_name: string;
}

// Foreign format identifiers — tables registered via Lakehouse Federation
export const FOREIGN_FORMATS = new Set([
  "SQLSERVER", "SNOWFLAKE", "MYSQL", "POSTGRESQL", "BIGQUERY",
  "ORACLE", "NETSUITE", "WORKDAY", "SALESFORCE",
]);

export interface TableInfo {
  name: string;
  full_name: string;
  table_type: "MANAGED" | "EXTERNAL" | "VIEW" | "FOREIGN";
  data_source_format: string | null;
  size_bytes: number | null;
  row_count: number | null;
  storage_location: string | null;
  external_engine_read_support: boolean;
  read_support_reason?: string;
  columns: { name: string; type_text: string }[];
}

// --- Routing log (live pipeline events) ---
export type RoutingLogLevel = "info" | "rule" | "decision" | "warn" | "error";

export interface RoutingLogEvent {
  timestamp: string; // HH:MM:SS.mmm
  level: RoutingLogLevel;
  stage: string; // e.g. "parse", "rules", "ml_model", "engine", "execute", "complete"
  message: string;
}

// --- Query log ---
export interface LogEntry {
  correlation_id: string;
  timestamp: string;
  query_text: string;
  engine: string;
  engine_display_name: string;
  status: "running" | "success" | "error";
  latency_ms: number;
  cost_usd: number;
  // Per-query detail data (populated after execution)
  routing_decision?: QueryExecutionResult["routing_decision"];
  routing_events?: RoutingLogEvent[];
}

// --- Kept for backwards compat but no longer used for routing toggle ---
export type RoutingMode = "smart" | "duckdb" | "databricks";
