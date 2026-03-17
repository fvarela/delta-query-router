export interface HealthStatus {
  web_ui: { status: string; detail?: string };
  routing_service: { status: string; detail?: string };
  postgresql: { status: string; detail?: string };
  duckdb_worker: { status: string; detail?: string };
  databricks: { status: string; detail?: string };
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
}

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

export interface EngineCatalogEntry {
  id: number;
  engine_type: "databricks_sql" | "duckdb";
  display_name: string;
  config: Record<string, any>;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface EnginePreference {
  engine_id: string;
  display_name: string;
  engine_type: "databricks_sql" | "duckdb";
  preference_order: number;
}

export interface RoutingRule {
  id: number;
  priority: number;
  condition_type: string;
  condition_value: string;
  target_engine: string;
  is_system: boolean;
  enabled: boolean;
}

export interface RoutingSettings {
  time_weight: number;
  cost_weight: number;
}

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
}

export interface Model {
  id: number;
  linked_engines: string[];
  model_path: string;
  accuracy_metrics: {
    r_squared: number;
    mae_ms: number;
  };
  is_active: boolean;
  created_at: string;
}

export interface CatalogInfo {
  name: string;
}

export interface SchemaInfo {
  name: string;
  catalog_name: string;
}

export interface TableInfo {
  name: string;
  full_name: string;
  table_type: "MANAGED" | "EXTERNAL" | "VIEW";
  data_source_format: string | null;
  size_bytes: number | null;
  row_count: number | null;
  storage_location: string | null;
  external_engine_read_support: boolean;
  read_support_reason?: string;
  columns: { name: string; type_text: string }[];
}

export interface LogEntry {
  correlation_id: string;
  timestamp: string;
  query_text: string;
  engine: string;
  engine_display_name: string;
  status: "success" | "error";
  latency_ms: number;
  cost_usd: number;
}

export type RoutingMode = "smart" | "duckdb" | "databricks";
