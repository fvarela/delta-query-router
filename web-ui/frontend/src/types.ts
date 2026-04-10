// --- Auth ---
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
}

// --- Workspace ---
export interface Workspace {
  id: string;
  name: string;
  url: string;
  token: string | null; // PAT — transient only, never persisted to localStorage
  connected: boolean;
  username: string | null; // Databricks username, populated on connect
}

// --- Databricks settings (from GET /api/settings/databricks) ---
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
  cluster_size?: string;
  warehouse_type?: string;
  /** Engine ID matched by backend based on warehouse size (e.g. "databricks-serverless-2xs") */
  matched_engine_id?: string | null;
}

// --- Collections & Queries ---
export interface Collection {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  /** "tpcds" for built-in TPC-DS collections, "user" for user-created */
  tag?: "tpcds" | "user";
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

export type EngineScalePolicy = "always_on" | "scale_to_zero";

export interface EngineCatalogEntry {
  id: string;
  engine_type: "databricks_sql" | "duckdb";
  display_name: string;
  config: Record<string, any>;
  is_default: boolean;
  /** Enabled for benchmarking and routing (set in Manage Engines catalog) */
  enabled: boolean;
  cost_tier: number;
  runtime_state: EngineRuntimeState;
  scale_policy: EngineScalePolicy;
  scalable?: boolean;
  /** Number of routing profiles currently using this engine (Round 16 — DuckDB lock) */
  profile_usage_count?: number;
  created_at?: string;
  updated_at?: string;
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
  fit_weight: number;
  cost_weight: number;
  running_bonus_duckdb: number;
  running_bonus_databricks: number;
}

/** GET /api/routing/settings response — includes active_profile_id from default profile */
export interface RoutingSettingsResponse extends RoutingSettings {
  active_profile_id: number | null;
}

// --- Run mode ---
export type RunMode = "single" | "multi";

// --- Routing mode (user-selected) ---
export type RoutingMode = "single" | "smart" | "benchmark";

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
    // Scoring (ODQ-10)
    latency_score?: number;
    cost_score?: number;
    weighted_score?: number;
  };
  execution: {
    execution_time_ms: number;
  };
  columns: string[];
  rows: any[][];
}

// --- Benchmarks ---
export interface BenchmarkSummary {
  id: number;
  collection_id: number;
  collection_name?: string;
  status: "warming_up" | "running" | "complete" | "failed";
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
  cold_start_time_ms: number | null;
  started_at: string;
}

export interface BenchmarkResult {
  engine_id: string;
  engine_display_name: string;
  query_id: number;
  execution_time_ms: number | null;
  error_message?: string | null;
}

// --- ML Models (latency prediction only — cost uses static engine tiers per ODQ-14) ---
export interface SubModelMetrics {
  r_squared: number;
  mae_ms?: number;
  model_path: string;
}

export interface Model {
  id: number;
  linked_engines: string[];
  latency_model: SubModelMetrics;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
  benchmark_count?: number;
  training_queries?: number;
  training_collection_ids?: number[];
}

// --- Storage Latency Probes (ODQ-9) ---
export interface StorageLatencyProbe {
  id: number;
  storage_location: string;
  engine_id: string;
  engine_display_name?: string;
  probe_time_ms: number;
  bytes_read: number | null;
  measured_at: string;
}

// --- Unity Catalog ---
export interface CatalogInfo {
  name: string;
}

export interface SchemaInfo {
  name: string;
  catalog_name: string;
  external_use_schema?: boolean;
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
  // Per-query detail data (populated after execution)
  routing_decision?: QueryExecutionResult["routing_decision"];
  routing_events?: RoutingLogEvent[];
}

// --- Kept for backwards compat but no longer used for routing toggle ---
export type LegacyRoutingMode = "smart" | "duckdb" | "databricks";

// --- Benchmark Definitions & Runs (Phase 15 revised data model) ---
// A benchmark definition = collection × engine (1:1 immutable pair)
export interface BenchmarkDefinition {
  id: number;
  collection_id: number;
  collection_name: string;
  engine_id: string;
  engine_display_name: string;
  created_at: string;
  run_count: number;
  latest_run?: BenchmarkRunSummary;
}

// A benchmark run = single execution of a definition
export interface BenchmarkRunSummary {
  id: number;
  definition_id: number;
  status: "warming_up" | "running" | "complete" | "failed";
  created_at: string;
  updated_at: string;
}

export interface BenchmarkRunDetail extends BenchmarkRunSummary {
  warmups: BenchmarkWarmup[];
  results: BenchmarkResult[];
}

// --- Left panel tab ---
export type LeftPanelTab = "catalog" | "collections";

// --- Databricks warehouse mapping (Round 16) ---
// Maps a catalog engine type (e.g. "databricks:serverless-medium") to an actual warehouse in a workspace
export interface WarehouseMapping {
  engineId: string;           // catalog engine ID (e.g. "databricks:serverless-medium")
  warehouseId: string | null; // actual warehouse ID in the workspace (null = not mapped)
  warehouseName: string | null; // display name of the mapped warehouse
}

// --- Workspace binding (Round 16) ---
// A profile can be bound to a specific Databricks workspace
export interface WorkspaceBinding {
  workspaceId: string;        // references Workspace.id
  workspaceName: string;      // display label
  workspaceUrl: string;       // Databricks host URL
}

// --- Routing configuration snapshot (saved state) ---
export interface RoutingConfig {
  routingMode: RoutingMode;        // User-selected: "single" or "smart"
  singleEngineId: string | null;   // Selected engine in single mode
  activeModelId: number | null;    // Active ML model ID (smart mode)
  enabledEngineIds: string[];      // IDs of enabled engines (smart mode — subset of model's linked_engines)
  routingPriority: number;         // cost_weight value (0 | 0.5 | 1)
  workspaceBinding: WorkspaceBinding | null; // Databricks workspace for this profile (Round 16)
  warehouseMappings: WarehouseMapping[];     // Databricks engine → warehouse mappings (Round 16)
}

// --- Routing Profiles (persistent named configs — Round 13) ---
export interface RoutingProfile {
  id: number;
  name: string;
  is_default: boolean;
  config: RoutingConfig;
  created_at: string;
  updated_at: string;
}

// --- Discovered warehouses for a connected workspace (Round 16) ---
// Grouped by engine type for the UI to show "2 warehouses found" etc.
export interface DiscoveredWarehouse {
  id: string;
  name: string;
  state: string;
  cluster_size: string;
  warehouse_type: string;         // "PRO", "CLASSIC", "SERVERLESS"
  matchingEngineId: string | null; // which catalog engine type this matches (null if no match)
}

// --- Metastore external access (Phase 14 / REQ-001) ---
export interface MetastoreAccessStatus {
  external_access_enabled: boolean;
  metastore_name: string;
}

// --- TPC-DS (Phase 14 / REQ-004–REQ-012) ---
export type TpcdsStatus = "creating" | "ready" | "failed" | "deleting";

export interface TpcdsPreFlight {
  samples_available: boolean;
  metastore_external_access: boolean;
  warehouse_configured: boolean;
}

export interface TpcdsCreateRequest {
  catalog_name: string;
  schema_name: string;
  scale_factor: number;
}

export interface TpcdsCreateResponse {
  id: number;
  catalog_name: string;
  schema_name: string;
  scale_factor: number;
  status: TpcdsStatus;
  method: "ctas" | "job";
  job_run_id?: string;
}

export interface TpcdsCatalog {
  id: number;
  catalog_name: string;
  schema_name: string;
  scale_factor: number;
  status: TpcdsStatus;
  tables_created: number;
  total_tables: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TpcdsStatusResponse extends TpcdsCatalog {
  job_run_id: string | null;
  job_state?: string;
  elapsed_time_seconds?: number;
}
