// =============================================================================
// Mock data for Engine Setup view (Phase 15 frontend exploration)
// =============================================================================
// Provides realistic mock data for:
//   - Engine catalog (6 engines: 3 DuckDB + 3 Databricks)
//   - Benchmark definitions (collection × engine pairs)
//   - Benchmark runs (executions of definitions)
//   - Benchmark results (per-query timings)
//   - ML Models
// =============================================================================

import type {
  EngineCatalogEntry,
  BenchmarkDefinition,
  BenchmarkRunSummary,
  BenchmarkRunDetail,
  BenchmarkWarmup,
  BenchmarkResult,
  Model,
  Collection,
  CollectionWithQueries,
  RoutingProfile,
  DiscoveredWarehouse,
  Workspace,
} from "../types";

// ---- Engine Catalog (6 predefined engines) ----
export const MOCK_ENGINES: EngineCatalogEntry[] = [
  {
    id: "duckdb:1gb-1cpu",
    engine_type: "duckdb",
    display_name: "DuckDB Small",
    config: { memory_gb: 1, cpu_count: 1 },
    is_default: true,
    enabled: true,
    cost_tier: 1,
    runtime_state: "running",
    scale_policy: "always_on",
    scalable: true,
    profile_usage_count: 2, // Used by "Production — Balanced" and "Dev — DuckDB Only"
  },
  {
    id: "duckdb:4gb-2cpu",
    engine_type: "duckdb",
    display_name: "DuckDB Medium",
    config: { memory_gb: 4, cpu_count: 2 },
    is_default: true,
    enabled: true,
    cost_tier: 3,
    runtime_state: "running",
    scale_policy: "always_on",
    scalable: true,
    profile_usage_count: 2, // Used by "Production — Balanced" and "Full Fleet"
  },
  {
    id: "duckdb:8gb-4cpu",
    engine_type: "duckdb",
    display_name: "DuckDB Large",
    config: { memory_gb: 8, cpu_count: 4 },
    is_default: true,
    enabled: false,
    cost_tier: 5,
    runtime_state: "stopped",
    scale_policy: "scale_to_zero",
    scalable: true,
    profile_usage_count: 1, // Used by "Full Fleet"
  },
  {
    id: "databricks:serverless-2xs",
    engine_type: "databricks_sql",
    display_name: "Databricks 2X-Small",
    config: { cluster_size: "2X-Small", is_serverless: true },
    is_default: true,
    enabled: true,
    cost_tier: 6,
    runtime_state: "running",
    scale_policy: "always_on",
    scalable: false,
    profile_usage_count: 2,
  },
  {
    id: "databricks:serverless-medium",
    engine_type: "databricks_sql",
    display_name: "Databricks Medium",
    config: { cluster_size: "Medium", is_serverless: true },
    is_default: true,
    enabled: false,
    cost_tier: 8,
    runtime_state: "stopped",
    scale_policy: "scale_to_zero",
    scalable: false,
    profile_usage_count: 1,
  },
  {
    id: "databricks:serverless-large",
    engine_type: "databricks_sql",
    display_name: "Databricks Large",
    config: { cluster_size: "Large", is_serverless: true },
    is_default: true,
    enabled: false,
    cost_tier: 10,
    runtime_state: "stopped",
    scale_policy: "scale_to_zero",
    scalable: false,
    profile_usage_count: 0,
  },
];

// ---- Collections ----
export const MOCK_COLLECTIONS: Collection[] = [
  { id: 1, name: "TPC-DS 1GB", description: "TPC-DS benchmark at scale factor 1", created_at: "2026-03-20T10:00:00Z", updated_at: "2026-03-20T10:00:00Z", tag: "tpcds" },
  { id: 2, name: "TPC-DS 10GB", description: "TPC-DS benchmark at scale factor 10", created_at: "2026-03-20T10:00:00Z", updated_at: "2026-03-20T10:00:00Z", tag: "tpcds" },
  { id: 3, name: "Custom Analytics", description: "Custom analytical queries for business reporting", created_at: "2026-03-25T14:00:00Z", updated_at: "2026-04-01T09:00:00Z", tag: "user" },
];

// ---- Benchmark Definitions (collection × engine pairs) ----
export const MOCK_BENCHMARK_DEFINITIONS: BenchmarkDefinition[] = [
  // TPC-DS 1GB on 4 engines
  {
    id: 1,
    collection_id: 1,
    collection_name: "TPC-DS 1GB",
    engine_id: "duckdb:1gb-1cpu",
    engine_display_name: "DuckDB Small",
    created_at: "2026-03-25T10:00:00Z",
    run_count: 3,
    latest_run: { id: 3, definition_id: 1, status: "complete", created_at: "2026-04-01T10:00:00Z", updated_at: "2026-04-01T10:05:00Z" },
  },
  {
    id: 2,
    collection_id: 1,
    collection_name: "TPC-DS 1GB",
    engine_id: "duckdb:4gb-2cpu",
    engine_display_name: "DuckDB Medium",
    created_at: "2026-03-25T10:00:00Z",
    run_count: 3,
    latest_run: { id: 6, definition_id: 2, status: "complete", created_at: "2026-04-01T10:10:00Z", updated_at: "2026-04-01T10:14:00Z" },
  },
  {
    id: 3,
    collection_id: 1,
    collection_name: "TPC-DS 1GB",
    engine_id: "databricks:serverless-2xs",
    engine_display_name: "Databricks 2X-Small",
    created_at: "2026-03-25T10:00:00Z",
    run_count: 2,
    latest_run: { id: 8, definition_id: 3, status: "complete", created_at: "2026-04-01T10:20:00Z", updated_at: "2026-04-01T10:28:00Z" },
  },
  {
    id: 4,
    collection_id: 1,
    collection_name: "TPC-DS 1GB",
    engine_id: "databricks:serverless-medium",
    engine_display_name: "Databricks Medium",
    created_at: "2026-03-26T09:00:00Z",
    run_count: 1,
    latest_run: { id: 9, definition_id: 4, status: "complete", created_at: "2026-03-26T09:00:00Z", updated_at: "2026-03-26T09:06:00Z" },
  },
  // TPC-DS 10GB on 2 engines
  {
    id: 5,
    collection_id: 2,
    collection_name: "TPC-DS 10GB",
    engine_id: "duckdb:4gb-2cpu",
    engine_display_name: "DuckDB Medium",
    created_at: "2026-03-28T14:00:00Z",
    run_count: 2,
    latest_run: { id: 11, definition_id: 5, status: "complete", created_at: "2026-03-30T14:00:00Z", updated_at: "2026-03-30T14:20:00Z" },
  },
  {
    id: 6,
    collection_id: 2,
    collection_name: "TPC-DS 10GB",
    engine_id: "databricks:serverless-2xs",
    engine_display_name: "Databricks 2X-Small",
    created_at: "2026-03-28T14:00:00Z",
    run_count: 2,
    latest_run: { id: 12, definition_id: 6, status: "complete", created_at: "2026-03-30T14:30:00Z", updated_at: "2026-03-30T14:45:00Z" },
  },
  // Custom Analytics on 1 engine
  {
    id: 7,
    collection_id: 3,
    collection_name: "Custom Analytics",
    engine_id: "duckdb:1gb-1cpu",
    engine_display_name: "DuckDB Small",
    created_at: "2026-04-02T11:00:00Z",
    run_count: 1,
    latest_run: { id: 13, definition_id: 7, status: "complete", created_at: "2026-04-02T11:00:00Z", updated_at: "2026-04-02T11:03:00Z" },
  },
];

// ---- Helper: generate mock benchmark results for a run ----
const QUERY_NAMES = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10"];

function mockRunResults(engineId: string, queryCount: number = 10): BenchmarkResult[] {
  // Base latencies differ by engine type and size
  const baseMs: Record<string, number> = {
    "duckdb:1gb-1cpu": 80,
    "duckdb:4gb-2cpu": 45,
    "duckdb:8gb-4cpu": 30,
    "databricks:serverless-2xs": 180,
    "databricks:serverless-medium": 120,
    "databricks:serverless-large": 90,
  };
  const base = baseMs[engineId] ?? 100;
  const engineName = MOCK_ENGINES.find(e => e.id === engineId)?.display_name ?? engineId;

  return Array.from({ length: queryCount }, (_, i) => ({
    engine_id: engineId,
    engine_display_name: engineName,
    query_id: i + 1,
    execution_time_ms: Math.round(base + Math.random() * base * 2 + i * 5),
    error_message: null,
  }));
}

// ---- Benchmark Run Details (keyed by run ID) ----
// All runs across all definitions — multiple runs per definition to show history
export const MOCK_BENCHMARK_RUN_DETAILS: Record<number, BenchmarkRunDetail> = {
  // Definition 1: TPC-DS 1GB × DuckDB Small — 3 runs
  1: {
    id: 1, definition_id: 1, status: "complete",
    created_at: "2026-03-25T10:00:00Z", updated_at: "2026-03-25T10:04:00Z",
    warmups: [{ engine_id: "duckdb:1gb-1cpu", engine_display_name: "DuckDB Small", cold_start_time_ms: 1500, started_at: "2026-03-25T10:00:00Z" }],
    results: mockRunResults("duckdb:1gb-1cpu"),
  },
  2: {
    id: 2, definition_id: 1, status: "complete",
    created_at: "2026-03-28T10:00:00Z", updated_at: "2026-03-28T10:04:30Z",
    warmups: [{ engine_id: "duckdb:1gb-1cpu", engine_display_name: "DuckDB Small", cold_start_time_ms: 1350, started_at: "2026-03-28T10:00:00Z" }],
    results: mockRunResults("duckdb:1gb-1cpu"),
  },
  3: {
    id: 3, definition_id: 1, status: "complete",
    created_at: "2026-04-01T10:00:00Z", updated_at: "2026-04-01T10:05:00Z",
    warmups: [{ engine_id: "duckdb:1gb-1cpu", engine_display_name: "DuckDB Small", cold_start_time_ms: 1200, started_at: "2026-04-01T10:00:00Z" }],
    results: mockRunResults("duckdb:1gb-1cpu"),
  },
  // Definition 2: TPC-DS 1GB × DuckDB Medium — 3 runs
  4: {
    id: 4, definition_id: 2, status: "complete",
    created_at: "2026-03-25T10:10:00Z", updated_at: "2026-03-25T10:13:00Z",
    warmups: [{ engine_id: "duckdb:4gb-2cpu", engine_display_name: "DuckDB Medium", cold_start_time_ms: 950, started_at: "2026-03-25T10:10:00Z" }],
    results: mockRunResults("duckdb:4gb-2cpu"),
  },
  5: {
    id: 5, definition_id: 2, status: "complete",
    created_at: "2026-03-28T10:10:00Z", updated_at: "2026-03-28T10:13:30Z",
    warmups: [{ engine_id: "duckdb:4gb-2cpu", engine_display_name: "DuckDB Medium", cold_start_time_ms: 850, started_at: "2026-03-28T10:10:00Z" }],
    results: mockRunResults("duckdb:4gb-2cpu"),
  },
  6: {
    id: 6, definition_id: 2, status: "complete",
    created_at: "2026-04-01T10:10:00Z", updated_at: "2026-04-01T10:14:00Z",
    warmups: [{ engine_id: "duckdb:4gb-2cpu", engine_display_name: "DuckDB Medium", cold_start_time_ms: 800, started_at: "2026-04-01T10:10:00Z" }],
    results: mockRunResults("duckdb:4gb-2cpu"),
  },
  // Definition 3: TPC-DS 1GB × Databricks 2X-Small — 2 runs
  7: {
    id: 7, definition_id: 3, status: "complete",
    created_at: "2026-03-28T10:20:00Z", updated_at: "2026-03-28T10:27:00Z",
    warmups: [{ engine_id: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", cold_start_time_ms: 3600, started_at: "2026-03-28T10:20:00Z" }],
    results: mockRunResults("databricks:serverless-2xs"),
  },
  8: {
    id: 8, definition_id: 3, status: "complete",
    created_at: "2026-04-01T10:20:00Z", updated_at: "2026-04-01T10:28:00Z",
    warmups: [{ engine_id: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", cold_start_time_ms: 3400, started_at: "2026-04-01T10:20:00Z" }],
    results: mockRunResults("databricks:serverless-2xs"),
  },
  // Definition 4: TPC-DS 1GB × Databricks Medium — 1 run
  9: {
    id: 9, definition_id: 4, status: "complete",
    created_at: "2026-03-26T09:00:00Z", updated_at: "2026-03-26T09:06:00Z",
    warmups: [{ engine_id: "databricks:serverless-medium", engine_display_name: "Databricks Medium", cold_start_time_ms: 2800, started_at: "2026-03-26T09:00:00Z" }],
    results: mockRunResults("databricks:serverless-medium"),
  },
  // Definition 5: TPC-DS 10GB × DuckDB Medium — 2 runs
  10: {
    id: 10, definition_id: 5, status: "complete",
    created_at: "2026-03-28T14:00:00Z", updated_at: "2026-03-28T14:18:00Z",
    warmups: [{ engine_id: "duckdb:4gb-2cpu", engine_display_name: "DuckDB Medium", cold_start_time_ms: 900, started_at: "2026-03-28T14:00:00Z" }],
    results: mockRunResults("duckdb:4gb-2cpu"),
  },
  11: {
    id: 11, definition_id: 5, status: "complete",
    created_at: "2026-03-30T14:00:00Z", updated_at: "2026-03-30T14:20:00Z",
    warmups: [{ engine_id: "duckdb:4gb-2cpu", engine_display_name: "DuckDB Medium", cold_start_time_ms: 820, started_at: "2026-03-30T14:00:00Z" }],
    results: mockRunResults("duckdb:4gb-2cpu"),
  },
  // Definition 6: TPC-DS 10GB × Databricks 2X-Small — 2 runs
  12: {
    id: 12, definition_id: 6, status: "complete",
    created_at: "2026-03-30T14:30:00Z", updated_at: "2026-03-30T14:45:00Z",
    warmups: [{ engine_id: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", cold_start_time_ms: 3500, started_at: "2026-03-30T14:30:00Z" }],
    results: mockRunResults("databricks:serverless-2xs"),
  },
  14: {
    id: 14, definition_id: 6, status: "complete",
    created_at: "2026-04-02T08:00:00Z", updated_at: "2026-04-02T08:12:00Z",
    warmups: [{ engine_id: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", cold_start_time_ms: 3300, started_at: "2026-04-02T08:00:00Z" }],
    results: mockRunResults("databricks:serverless-2xs"),
  },
  // Definition 7: Custom Analytics × DuckDB Small — 1 run
  13: {
    id: 13, definition_id: 7, status: "complete",
    created_at: "2026-04-02T11:00:00Z", updated_at: "2026-04-02T11:03:00Z",
    warmups: [{ engine_id: "duckdb:1gb-1cpu", engine_display_name: "DuckDB Small", cold_start_time_ms: 1100, started_at: "2026-04-02T11:00:00Z" }],
    results: mockRunResults("duckdb:1gb-1cpu", 3), // Custom Analytics only has 3 queries
  },
};

/** Look up all runs for a given definition, sorted newest-first */
export function getRunsForDefinition(definitionId: number): BenchmarkRunDetail[] {
  return Object.values(MOCK_BENCHMARK_RUN_DETAILS)
    .filter(r => r.definition_id === definitionId)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
}

// ---- ML Models ----
export const MOCK_MODELS: Model[] = [
  {
    id: 1,
    linked_engines: ["duckdb:1gb-1cpu", "duckdb:4gb-2cpu", "databricks:serverless-2xs"],
    latency_model: { r_squared: 0.92, mae_ms: 12.4, model_path: "/models/latency_v1.joblib" },
    is_active: true,
    created_at: "2026-04-01T11:00:00Z",
    benchmark_count: 6,
    training_queries: 60,
    training_collection_ids: [1, 2], // TPC-DS 1GB + TPC-DS 10GB
  },
  {
    id: 2,
    linked_engines: ["duckdb:1gb-1cpu", "duckdb:4gb-2cpu", "duckdb:8gb-4cpu", "databricks:serverless-2xs", "databricks:serverless-medium"],
    latency_model: { r_squared: 0.87, mae_ms: 18.7, model_path: "/models/latency_v2.joblib" },
    is_active: false,
    created_at: "2026-03-28T15:00:00Z",
    benchmark_count: 8,
    training_queries: 80,
    training_collection_ids: [1], // TPC-DS 1GB only
  },
];

// ---- Mock Collections with Queries (for mock mode) ----
const TPCDS_QUERIES = [
  "SELECT c_customer_id, c_first_name, c_last_name, SUM(ss_net_paid) FROM customer JOIN store_sales ON c_customer_sk = ss_customer_sk GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 100",
  "SELECT d_year, brand_id, SUM(ss_ext_sales_price) sum_agg FROM date_dim JOIN store_sales ON d_date_sk = ss_sold_date_sk JOIN item ON ss_item_sk = i_item_sk WHERE i_manufact_id = 128 GROUP BY d_year, brand_id ORDER BY d_year, sum_agg DESC",
  "SELECT dt.d_year, item.i_brand_id, item.i_brand, SUM(ss_ext_sales_price) FROM date_dim dt JOIN store_sales ON dt.d_date_sk = ss_sold_date_sk JOIN item ON ss_item_sk = i_item_sk WHERE i_manufact_id = 128 AND d_moy = 11 GROUP BY 1,2,3",
  "SELECT i_item_id, AVG(ss_quantity) avg_qty, AVG(ss_list_price) avg_lp, AVG(ss_coupon_amt) avg_ca, COUNT(*) cnt FROM store_sales JOIN customer_demographics ON ss_cdemo_sk = cd_demo_sk JOIN item ON ss_item_sk = i_item_sk WHERE cd_gender = 'M' GROUP BY i_item_id ORDER BY i_item_id LIMIT 100",
  "SELECT s_store_name, SUM(ss_net_profit) FROM store_sales JOIN date_dim ON ss_sold_date_sk = d_date_sk JOIN store ON ss_store_sk = s_store_sk WHERE d_year = 2000 GROUP BY s_store_name ORDER BY s_store_name",
  "SELECT i_item_id, i_item_desc, SUM(cs_ext_sales_price) total FROM catalog_sales JOIN item ON cs_item_sk = i_item_sk JOIN date_dim ON cs_sold_date_sk = d_date_sk WHERE d_year BETWEEN 1999 AND 2001 GROUP BY 1,2 ORDER BY total DESC LIMIT 100",
  "SELECT ca_state, cd_gender, cd_dep_count, COUNT(*) cnt FROM customer_address JOIN customer ON ca_address_sk = c_current_addr_sk JOIN customer_demographics ON cd_demo_sk = c_current_cdemo_sk GROUP BY 1,2,3 ORDER BY cnt DESC LIMIT 100",
  "SELECT w_warehouse_name, i_item_id, SUM(inv_quantity_on_hand) qty FROM inventory JOIN warehouse ON inv_warehouse_sk = w_warehouse_sk JOIN item ON inv_item_sk = i_item_sk JOIN date_dim ON inv_date_sk = d_date_sk WHERE d_year = 2001 GROUP BY 1,2 ORDER BY qty DESC LIMIT 100",
  "SELECT cc_call_center_id, cc_name, cc_manager, SUM(cr_net_loss) FROM catalog_returns JOIN date_dim ON cr_returned_date_sk = d_date_sk JOIN call_center ON cr_call_center_sk = cc_call_center_sk WHERE d_year = 1998 AND d_moy = 11 GROUP BY 1,2,3",
  "SELECT cd_gender, cd_marital_status, cd_education_status, COUNT(*) cnt, AVG(cd_purchase_estimate) avg_pe FROM customer_demographics GROUP BY 1,2,3 ORDER BY cnt DESC LIMIT 100",
];

export const MOCK_COLLECTIONS_WITH_QUERIES: CollectionWithQueries[] = [
  {
    id: 1, name: "TPC-DS 1GB", description: "TPC-DS benchmark at scale factor 1",
    created_at: "2026-03-20T10:00:00Z", updated_at: "2026-03-20T10:00:00Z", tag: "tpcds",
    queries: TPCDS_QUERIES.map((q, i) => ({ id: 100 + i, collection_id: 1, query_text: q, sequence_number: i + 1 })),
  },
  {
    id: 2, name: "TPC-DS 10GB", description: "TPC-DS benchmark at scale factor 10",
    created_at: "2026-03-20T10:00:00Z", updated_at: "2026-03-20T10:00:00Z", tag: "tpcds",
    queries: TPCDS_QUERIES.map((q, i) => ({ id: 200 + i, collection_id: 2, query_text: q, sequence_number: i + 1 })),
  },
  {
    id: 3, name: "Custom Analytics", description: "Custom analytical queries for business reporting",
    created_at: "2026-03-25T14:00:00Z", updated_at: "2026-04-01T09:00:00Z", tag: "user",
    queries: [
      { id: 300, collection_id: 3, query_text: "SELECT region, SUM(revenue) AS total_rev FROM analytics.revenue_summary GROUP BY region ORDER BY total_rev DESC", sequence_number: 1 },
      { id: 301, collection_id: 3, query_text: "SELECT product_category, COUNT(DISTINCT customer_id) AS unique_customers FROM analytics.orders GROUP BY product_category", sequence_number: 2 },
      { id: 302, collection_id: 3, query_text: "SELECT DATE_TRUNC('month', order_date) AS month, SUM(amount) FROM analytics.orders GROUP BY 1 ORDER BY 1", sequence_number: 3 },
    ],
  },
];

/** Whether TPC-DS dataset is configured (mock toggle for UI dev) */
export const MOCK_TPCDS_CONFIGURED = true;

// ---- Routing Profiles (persistent named configs — Round 13, updated Round 16 with workspace binding) ----
export const MOCK_ROUTING_PROFILES: RoutingProfile[] = [
  {
    id: 1,
    name: "Production — Balanced",
    is_default: true,
    config: {
      routingMode: "smart",
      singleEngineId: null,
      activeModelId: 1,
      enabledEngineIds: ["duckdb:1gb-1cpu", "duckdb:4gb-2cpu", "databricks:serverless-2xs"],
      routingPriority: 0.5,
      workspaceBinding: {
        workspaceId: "ws-prod-01",
        workspaceName: "Production Workspace",
        workspaceUrl: "https://adb-1234567890.12.azuredatabricks.net",
      },
      warehouseMappings: [
        { engineId: "databricks:serverless-2xs", warehouseId: "abc123def456", warehouseName: "Prod Serverless XS" },
      ],
    },
    created_at: "2026-03-25T10:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
  },
  {
    id: 2,
    name: "Dev — DuckDB Only",
    is_default: false,
    config: {
      routingMode: "single",
      singleEngineId: "duckdb:1gb-1cpu",
      activeModelId: null,
      enabledEngineIds: [],
      routingPriority: 0,
      workspaceBinding: null,
      warehouseMappings: [],
    },
    created_at: "2026-03-26T14:00:00Z",
    updated_at: "2026-03-26T14:00:00Z",
  },
  {
    id: 3,
    name: "Full Fleet — Performance",
    is_default: false,
    config: {
      routingMode: "smart",
      singleEngineId: null,
      activeModelId: 2,
      enabledEngineIds: ["duckdb:1gb-1cpu", "duckdb:4gb-2cpu", "duckdb:8gb-4cpu", "databricks:serverless-2xs", "databricks:serverless-medium"],
      routingPriority: 0,
      workspaceBinding: {
        workspaceId: "ws-dev-01",
        workspaceName: "Development Workspace",
        workspaceUrl: "https://adb-9876543210.34.azuredatabricks.net",
      },
      warehouseMappings: [
        { engineId: "databricks:serverless-2xs", warehouseId: "dev-wh-xs-001", warehouseName: "Dev Serverless XS" },
        { engineId: "databricks:serverless-medium", warehouseId: "dev-wh-med-001", warehouseName: "Dev Medium WH" },
      ],
    },
    created_at: "2026-04-01T16:00:00Z",
    updated_at: "2026-04-01T16:00:00Z",
  },
];

// ---- Mock Discovered Warehouses (for a connected workspace) ----
// These simulate what `GET /api/databricks/warehouses` returns for a connected workspace
export const MOCK_DISCOVERED_WAREHOUSES: DiscoveredWarehouse[] = [
  {
    id: "abc123def456",
    name: "Prod Serverless XS",
    state: "RUNNING",
    cluster_size: "2X-Small",
    warehouse_type: "PRO",
    matchingEngineId: "databricks:serverless-2xs",
  },
  {
    id: "def456ghi789",
    name: "Dev Serverless XS",
    state: "STOPPED",
    cluster_size: "2X-Small",
    warehouse_type: "PRO",
    matchingEngineId: "databricks:serverless-2xs",
  },
  {
    id: "ghi789jkl012",
    name: "Prod Medium WH",
    state: "RUNNING",
    cluster_size: "Medium",
    warehouse_type: "PRO",
    matchingEngineId: "databricks:serverless-medium",
  },
  {
    id: "jkl012mno345",
    name: "Analytics Large",
    state: "STOPPED",
    cluster_size: "Large",
    warehouse_type: "PRO",
    matchingEngineId: "databricks:serverless-large",
  },
];

/** Get warehouses matching a specific catalog engine ID */
export function getWarehousesForEngine(engineId: string): DiscoveredWarehouse[] {
  return MOCK_DISCOVERED_WAREHOUSES.filter(w => w.matchingEngineId === engineId);
}

// ---- Mock Workspaces (for mock mode — left panel WorkspaceManager) ----
// The connected workspace matches the Production profile's workspace binding
export const MOCK_WORKSPACES: Workspace[] = [
  {
    id: "ws-prod-01",
    name: "Production Workspace",
    url: "https://adb-1234567890.12.azuredatabricks.net",
    token: null,
    connected: true,  // This one is connected by default in mock mode
    username: "admin@company.com",
  },
  {
    id: "ws-dev-01",
    name: "Development Workspace",
    url: "https://adb-9876543210.34.azuredatabricks.net",
    token: null,
    connected: false,
    username: null,
  },
];

/** Compute profile usage counts for engines from current profiles */
export function computeProfileUsageCounts(profiles: RoutingProfile[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const profile of profiles) {
    // Single mode: the selected engine is "in use"
    if (profile.config.routingMode === "single" && profile.config.singleEngineId) {
      counts[profile.config.singleEngineId] = (counts[profile.config.singleEngineId] ?? 0) + 1;
    }
    // Smart mode: all enabled engines are "in use"
    if (profile.config.routingMode === "smart") {
      for (const eid of profile.config.enabledEngineIds) {
        counts[eid] = (counts[eid] ?? 0) + 1;
      }
    }
  }
  return counts;
}
