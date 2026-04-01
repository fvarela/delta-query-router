// =============================================================================
// Mock API Layer
// =============================================================================
//
// REAL (wired to backend):
//   - catalog:       Unity Catalog browsing (catalogs, schemas, tables) — CatalogBrowser.tsx uses api.get() directly
//   - query:         SQL execution via POST /api/query — CenterPanel.tsx uses api.post() directly
//   - query logs:    query history via GET /api/logs — CenterPanel.tsx uses api.get() directly
//   - query detail:  GET /api/query/{id} — CenterPanel.tsx uses api.get() directly
//   - workspaces:    workspace connect/disconnect via POST /api/settings/databricks — WorkspaceManager.tsx uses api directly
//   - warehouses:    warehouse list + selection via GET /api/databricks/warehouses + PUT /api/settings/warehouse — AppContext + WorkspaceManager
//   - routing rules: GET/POST/DELETE /api/routing/rules — wired in Phase 8
//   - routing settings: GET/PUT /api/routing/settings — wired in Phase 8
//   - collections:   CRUD + query management via /api/collections — wired in Phase 10
//   - engines:       engine catalog + runtime status via /api/engines — wired in Phase 10
//
// MOCKED (backend endpoints not yet implemented):
//   - models:        ML model listing, activation, training wizard
//   - benchmarks:    benchmark lifecycle, results, storage probes
//   - probes:        storage latency probes
//
// All components import exclusively from this file via `mockApi`.
// When a real endpoint is available, replace the corresponding mock function
// body with a fetch/axios call — the function signature stays the same.
// =============================================================================

import type {
  Collection, CollectionWithQueries, Query,
  RoutingRule, RoutingSettings,
  QueryExecutionResult, BenchmarkSummary, BenchmarkDetail,
  Model, CatalogInfo, SchemaInfo, TableInfo, LogEntry,
  RoutingLogEvent, RoutingLogLevel, StorageLatencyProbe,
} from "../types";

import { api } from "../lib/api";

const delay = (ms: number) => new Promise(r => setTimeout(r, ms));

const logTs = () => {
  const d = new Date();
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}.${d.getMilliseconds().toString().padStart(3, "0")}`;
};

const mkLog = (level: RoutingLogLevel, stage: string, message: string): RoutingLogEvent => ({
  timestamp: logTs(), level, stage, message,
});

// ---- Mutable state ----
let nextRuleId = 100;
let nextModelId = 3;
let nextBenchmarkId = 4;

let storageLatencyProbes: StorageLatencyProbe[] = [
  { id: 1, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 12.3, bytes_read: 1048576, measured_at: "2026-03-14T09:00:30Z" },
  { id: 2, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", probe_time_ms: 11.8, bytes_read: 1048576, measured_at: "2026-03-14T09:00:30Z" },
  { id: 3, storage_location: "s3://delta-router/analytics/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 14.1, bytes_read: 1048576, measured_at: "2026-03-15T14:30:25Z" },
  { id: 4, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", probe_time_ms: 10.5, bytes_read: 1048576, measured_at: "2026-03-16T11:00:28Z" },
];

let routingRules: RoutingRule[] = [
  { id: 1, priority: 1, condition_type: "table_type", condition_value: "VIEW", target_engine: "databricks", is_system: true, enabled: true },
  { id: 2, priority: 2, condition_type: "has_governance", condition_value: "row_filter", target_engine: "databricks", is_system: true, enabled: true },
  { id: 3, priority: 10, condition_type: "table_name", condition_value: "store_sales", target_engine: "duckdb", is_system: false, enabled: true },
];

let routingSettings: RoutingSettings = { fit_weight: 0.5, cost_weight: 0.5, running_bonus_duckdb: 0.05, running_bonus_databricks: 0.15 };

let models: Model[] = [
  {
    id: 1,
    linked_engines: ["duckdb:2gb-2cpu", "databricks:serverless-2xs", "duckdb:8gb-4cpu"],
    latency_model: { r_squared: 0.87, mae_ms: 45, model_path: "/models/bundle_001_latency.joblib" },
    cost_model: { r_squared: 0.91, mae_usd: 0.0012, model_path: "/models/bundle_001_cost.joblib" },
    is_active: false, created_at: "2026-03-10T14:30:00Z", benchmark_count: 12, training_queries: 99,
  },
  {
    id: 2,
    linked_engines: ["duckdb:2gb-2cpu", "duckdb:8gb-4cpu"],
    latency_model: { r_squared: 0.79, mae_ms: 62, model_path: "/models/bundle_002_latency.joblib" },
    cost_model: { r_squared: 0.83, mae_usd: 0.0018, model_path: "/models/bundle_002_cost.joblib" },
    is_active: false, created_at: "2026-03-12T10:00:00Z", benchmark_count: 8, training_queries: 45,
  },
];

let queryLogs: LogEntry[] = [
  { correlation_id: "log-1", timestamp: "2026-03-15 10:45:12", query_text: "SELECT c_customer_sk, c_first_name, c_last_name FROM delta_router_dev.tpcds.customer WHERE c_birth_country = 'UNITED STATES' LIMIT 100", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 45 },
  { correlation_id: "log-2", timestamp: "2026-03-15 10:44:30", query_text: "SELECT ss_sold_date_sk, SUM(ss_net_profit) AS total_profit FROM delta_router_dev.tpcds.store_sales GROUP BY ss_sold_date_sk ORDER BY total_profit DESC LIMIT 20", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 890 },
  { correlation_id: "log-3", timestamp: "2026-03-15 10:43:15", query_text: "SELECT * FROM delta_router_dev.analytics.revenue_summary LIMIT 50", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "success", latency_ms: 340 },
  { correlation_id: "log-4", timestamp: "2026-03-15 10:42:00", query_text: "SELECT cd_gender, cd_education_status, COUNT(*) AS cnt FROM delta_router_dev.tpcds.customer_demographics GROUP BY cd_gender, cd_education_status", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 65 },
  { correlation_id: "log-5", timestamp: "2026-03-15 10:40:45", query_text: "SELECT * FROM delta_router_dev.tpcds.customer_pii LIMIT 100", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "success", latency_ms: 280 },
  { correlation_id: "log-6", timestamp: "2026-03-15 10:39:30", query_text: "SELECT d_date_sk, d_year FROM delta_router_dev.tpcds.date_dim WHERE d_year = 2024", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 30 },
  { correlation_id: "log-7", timestamp: "2026-03-15 10:38:00", query_text: "SELECT cs_sold_date_sk, cs_item_sk, cs_quantity FROM delta_router_dev.tpcds.catalog_sales WHERE cs_quantity > 50 LIMIT 100", engine: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", status: "success", latency_ms: 620 },
  { correlation_id: "log-8", timestamp: "2026-03-15 10:36:45", query_text: "INSERT INTO delta_router_dev.tpcds.customer VALUES (...)", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "error", latency_ms: 150 },
  { correlation_id: "log-9", timestamp: "2026-03-15 10:35:30", query_text: "SELECT COUNT(*) FROM delta_router_dev.tpcds.store_sales", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 22 },
  { correlation_id: "log-10", timestamp: "2026-03-15 10:34:00", query_text: "SELECT * FROM delta_router_dev.tpcds.customer WHERE c_customer_sk = 1", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 55 },
];

let benchmarks: BenchmarkDetail[] = [
  {
    id: 1, collection_id: 1, status: "complete", engine_count: 3, created_at: "2026-03-14T09:00:00Z", updated_at: "2026-03-14T09:05:00Z",
    warmups: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", cold_start_time_ms: 120, started_at: "2026-03-14T09:00:00Z" },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", cold_start_time_ms: 2400, started_at: "2026-03-14T09:00:00Z" },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", cold_start_time_ms: 180, started_at: "2026-03-14T09:00:00Z" },
    ],
    storage_probes: [
      { id: 1, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 12.3, bytes_read: 1048576, measured_at: "2026-03-14T09:00:30Z" },
      { id: 2, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", probe_time_ms: 11.8, bytes_read: 1048576, measured_at: "2026-03-14T09:00:30Z" },
    ],
    results: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 1, execution_time_ms: 45, data_scanned_bytes: 1200000, io_latency_ms: 12 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 1, execution_time_ms: 180, data_scanned_bytes: 1200000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 1, execution_time_ms: 38, data_scanned_bytes: 1200000, io_latency_ms: 11 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 2, execution_time_ms: 890, data_scanned_bytes: 52000000, io_latency_ms: 85 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 2, execution_time_ms: 320, data_scanned_bytes: 52000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 2, execution_time_ms: 450, data_scanned_bytes: 52000000, io_latency_ms: 78 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 3, execution_time_ms: 1200, data_scanned_bytes: 85000000, io_latency_ms: 140 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 3, execution_time_ms: 410, data_scanned_bytes: 85000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 3, execution_time_ms: 620, data_scanned_bytes: 85000000, io_latency_ms: 125 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 4, execution_time_ms: 65, data_scanned_bytes: 3000000, io_latency_ms: 8 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 4, execution_time_ms: 195, data_scanned_bytes: 3000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 4, execution_time_ms: 52, data_scanned_bytes: 3000000, io_latency_ms: 7 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 5, execution_time_ms: 30, data_scanned_bytes: 800000, io_latency_ms: 5 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 5, execution_time_ms: 160, data_scanned_bytes: 800000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 5, execution_time_ms: 25, data_scanned_bytes: 800000, io_latency_ms: 4 },
    ],
  },
  {
    id: 2, collection_id: 2, status: "complete", engine_count: 2, created_at: "2026-03-15T14:30:00Z", updated_at: "2026-03-15T14:33:00Z",
    warmups: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", cold_start_time_ms: 110, started_at: "2026-03-15T14:30:00Z" },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", cold_start_time_ms: 2100, started_at: "2026-03-15T14:30:00Z" },
    ],
    storage_probes: [
      { id: 3, storage_location: "s3://delta-router/analytics/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 14.1, bytes_read: 1048576, measured_at: "2026-03-15T14:30:25Z" },
    ],
    results: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 6, execution_time_ms: 55, data_scanned_bytes: 2400000, io_latency_ms: 14 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 6, execution_time_ms: 210, data_scanned_bytes: 2400000 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 7, execution_time_ms: 38, data_scanned_bytes: 1800000, io_latency_ms: 10 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 7, execution_time_ms: 165, data_scanned_bytes: 1800000 },
    ],
  },
  {
    id: 3, collection_id: 1, status: "complete", engine_count: 2, created_at: "2026-03-16T11:00:00Z", updated_at: "2026-03-16T11:04:00Z",
    warmups: [
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", cold_start_time_ms: 150, started_at: "2026-03-16T11:00:00Z" },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", cold_start_time_ms: 2250, started_at: "2026-03-16T11:00:00Z" },
    ],
    storage_probes: [
      { id: 4, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", probe_time_ms: 10.5, bytes_read: 1048576, measured_at: "2026-03-16T11:00:28Z" },
    ],
    results: [
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 1, execution_time_ms: 35, data_scanned_bytes: 1200000, io_latency_ms: 10 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 1, execution_time_ms: 175, data_scanned_bytes: 1200000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 2, execution_time_ms: 420, data_scanned_bytes: 52000000, io_latency_ms: 72 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 2, execution_time_ms: 310, data_scanned_bytes: 52000000 },
    ],
  },
];

// ---- Table data ----
const tableData: Record<string, TableInfo[]> = {
  "delta_router_dev.tpcds": [
    { name: "customer", full_name: "delta_router_dev.tpcds.customer", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 47185920, row_count: 100000, storage_location: "abfss://tpcds@deltarouter.dfs.core.windows.net/customer", external_engine_read_support: true, columns: [{ name: "c_customer_sk", type_text: "INT" }, { name: "c_customer_id", type_text: "STRING" }, { name: "c_first_name", type_text: "STRING" }, { name: "c_last_name", type_text: "STRING" }, { name: "c_birth_country", type_text: "STRING" }, { name: "c_email_address", type_text: "STRING" }] },
    { name: "store_sales", full_name: "delta_router_dev.tpcds.store_sales", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 2254857830, row_count: 28000000, storage_location: "abfss://tpcds@deltarouter.dfs.core.windows.net/store_sales", external_engine_read_support: true, columns: [{ name: "ss_sold_date_sk", type_text: "INT" }, { name: "ss_item_sk", type_text: "INT" }, { name: "ss_customer_sk", type_text: "INT" }, { name: "ss_net_profit", type_text: "DECIMAL(7,2)" }, { name: "ss_quantity", type_text: "INT" }] },
    { name: "catalog_sales", full_name: "delta_router_dev.tpcds.catalog_sales", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 3650722202, row_count: 43000000, storage_location: "abfss://secure@securedatalake.dfs.core.windows.net/catalog_sales", external_engine_read_support: true, columns: [{ name: "cs_sold_date_sk", type_text: "INT" }, { name: "cs_item_sk", type_text: "INT" }, { name: "cs_quantity", type_text: "INT" }, { name: "cs_net_profit", type_text: "DECIMAL(7,2)" }] },
    { name: "customer_demographics", full_name: "delta_router_dev.tpcds.customer_demographics", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 12582912, row_count: 1920000, storage_location: "abfss://secure@securedatalake.dfs.core.windows.net/customer_demographics", external_engine_read_support: true, columns: [{ name: "cd_demo_sk", type_text: "INT" }, { name: "cd_gender", type_text: "STRING" }, { name: "cd_education_status", type_text: "STRING" }, { name: "cd_credit_rating", type_text: "STRING" }] },
    { name: "date_dim", full_name: "delta_router_dev.tpcds.date_dim", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 5242880, row_count: 73049, storage_location: "abfss://private@privatestore.dfs.core.windows.net/date_dim", external_engine_read_support: true, columns: [{ name: "d_date_sk", type_text: "INT" }, { name: "d_date_id", type_text: "STRING" }, { name: "d_year", type_text: "INT" }, { name: "d_quarter_name", type_text: "STRING" }, { name: "d_month_seq", type_text: "INT" }] },
    { name: "web_sales", full_name: "delta_router_dev.tpcds.web_sales", table_type: "EXTERNAL", data_source_format: "ICEBERG", size_bytes: 1890000000, row_count: 18000000, storage_location: "abfss://private@privatestore.dfs.core.windows.net/web_sales", external_engine_read_support: true, columns: [{ name: "ws_sold_date_sk", type_text: "INT" }, { name: "ws_item_sk", type_text: "INT" }, { name: "ws_bill_customer_sk", type_text: "INT" }, { name: "ws_net_profit", type_text: "DECIMAL(7,2)" }, { name: "ws_quantity", type_text: "INT" }] },
  ],
  "delta_router_dev.analytics": [
    { name: "revenue_summary", full_name: "delta_router_dev.analytics.revenue_summary", table_type: "VIEW", data_source_format: null, size_bytes: null, row_count: null, storage_location: null, external_engine_read_support: false, read_support_reason: "View — must execute on Databricks", columns: [{ name: "year", type_text: "INT" }, { name: "quarter", type_text: "STRING" }, { name: "total_revenue", type_text: "DECIMAL(12,2)" }, { name: "total_cost", type_text: "DECIMAL(12,2)" }] },
    { name: "customer_pii", full_name: "delta_router_dev.analytics.customer_pii", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 241172480, row_count: 1000000, storage_location: "abfss://analytics@analyticsstore.dfs.core.windows.net/customer_pii", external_engine_read_support: false, read_support_reason: "Has row-level security filter", columns: [{ name: "customer_id", type_text: "INT" }, { name: "ssn", type_text: "STRING" }, { name: "full_name", type_text: "STRING" }, { name: "email", type_text: "STRING" }, { name: "phone", type_text: "STRING" }] },
  ],
  "delta_router_dev.external": [
    { name: "sqlserver_orders", full_name: "delta_router_dev.external.sqlserver_orders", table_type: "FOREIGN", data_source_format: "SQLSERVER", size_bytes: null, row_count: null, storage_location: null, external_engine_read_support: false, read_support_reason: "Foreign table (SQL Server) — must route via Databricks", columns: [{ name: "order_id", type_text: "INT" }, { name: "customer_id", type_text: "INT" }, { name: "order_date", type_text: "DATE" }, { name: "total_amount", type_text: "DECIMAL(10,2)" }, { name: "status", type_text: "VARCHAR(50)" }] },
    { name: "snowflake_inventory", full_name: "delta_router_dev.external.snowflake_inventory", table_type: "FOREIGN", data_source_format: "SNOWFLAKE", size_bytes: null, row_count: null, storage_location: null, external_engine_read_support: false, read_support_reason: "Foreign table (Snowflake) — must route via Databricks", columns: [{ name: "product_id", type_text: "INT" }, { name: "warehouse_id", type_text: "INT" }, { name: "quantity", type_text: "INT" }, { name: "last_updated", type_text: "TIMESTAMP" }] },
  ],
};

// ---- Mock API ----
export const mockApi = {
  // Catalog browser
  async getCatalogs(): Promise<CatalogInfo[]> {
    // TODO: Replace with real API call — GET /api/catalog/catalogs
    await delay(300);
    return [{ name: "delta_router_dev" }];
  },

  async getSchemas(_catalog: string): Promise<SchemaInfo[]> {
    // TODO: Replace with real API call — GET /api/catalog/:catalog/schemas
    await delay(300);
    return [
      { name: "tpcds", catalog_name: "delta_router_dev" },
      { name: "analytics", catalog_name: "delta_router_dev" },
      { name: "external", catalog_name: "delta_router_dev" },
    ];
  },

  async getTables(catalog: string, schema: string): Promise<TableInfo[]> {
    // TODO: Replace with real API call — GET /api/catalog/:catalog/:schema/tables
    await delay(400);
    return tableData[`${catalog}.${schema}`] || [];
  },

  // Collections (real — wired to /api/collections)
  async getCollections(): Promise<Collection[]> {
    return api.get<Collection[]>('/api/collections');
  },

  async getCollection(id: number): Promise<CollectionWithQueries> {
    return api.get<CollectionWithQueries>(`/api/collections/${id}`);
  },

  async createCollection(name: string, description: string): Promise<Collection> {
    return api.post<Collection>('/api/collections', { name, description });
  },

  async updateCollection(id: number, data: Partial<Collection>): Promise<Collection> {
    return api.put<Collection>(`/api/collections/${id}`, data);
  },

  async deleteCollection(id: number): Promise<void> {
    await api.del(`/api/collections/${id}`);
  },

  async addQuery(collectionId: number, queryText: string): Promise<Query> {
    return api.post<Query>(`/api/collections/${collectionId}/queries`, { query_text: queryText });
  },

  async deleteQuery(collectionId: number, queryId: number): Promise<void> {
    await api.del(`/api/collections/${collectionId}/queries/${queryId}`);
  },

  // Query Execution
  async executeQuery(sql: string, routingMode: string, onLog?: (event: RoutingLogEvent) => void): Promise<QueryExecutionResult> {
    // TODO: Replace with real API call — POST /api/query/execute
    const collectedEvents: RoutingLogEvent[] = [];
    const emit = async (level: RoutingLogLevel, stage: string, message: string, delayMs = 80 + Math.random() * 120) => {
      const ev = mkLog(level, stage, message);
      collectedEvents.push(ev);
      if (onLog) {
        await delay(delayMs);
        onLog(ev);
      }
    };

    const sqlLower = sql.toLowerCase();
    const correlationId = `q-${Date.now()}`;

    // Register a "running" entry immediately in query history
    const runningEntry: LogEntry = {
      correlation_id: correlationId,
      timestamp: new Date().toISOString().replace("T", " ").slice(0, 19),
      query_text: sql,
      engine: "",
      engine_display_name: "",
      status: "running",
      latency_ms: 0,
      routing_events: collectedEvents, // live reference — grows as events stream
    };
    queryLogs.unshift(runningEntry);

    // --- Phase 1: Parse ---
    await emit("info", "parse", `Received query (${sql.length} chars), correlation_id=${correlationId}`, 50);
    await emit("info", "parse", `Parsing SQL statement...`, 100 + Math.random() * 100);

    // Detect tables referenced
    const tableHints: string[] = [];
    for (const t of ["revenue_summary", "customer_pii", "customer_demographics", "store_sales", "customer", "catalog_sales", "date_dim", "web_sales", "sqlserver_orders", "snowflake_inventory"]) {
      if (sqlLower.includes(t)) tableHints.push(t);
    }
    await emit("info", "parse", `Tables referenced: ${tableHints.length > 0 ? tableHints.join(", ") : "(inline/unknown)"}`, 60);

    // Detect statement type
    const stmtType = sqlLower.trimStart().startsWith("select") ? "SELECT" : sqlLower.trimStart().startsWith("insert") ? "INSERT" : "OTHER";
    await emit("info", "parse", `Statement type: ${stmtType}`, 40);

    // --- Phase 2: Routing rules ---
    let engine: string, engineName: string, stage: "mandatory_rule" | "user_rule" | "ml_prediction" | "fallback", reason: string, execTime: number, complexity: number;

    await emit("info", "rules", `Evaluating routing rules...`, 100 + Math.random() * 80);

    if (sqlLower.includes("sqlserver_orders") || sqlLower.includes("snowflake_inventory")) {
      const foreignSource = sqlLower.includes("sqlserver_orders") ? "SQL Server" : "Snowflake";
      await emit("rule", "rules", `Rule #SYS-0 [mandatory]: table is a foreign/federated table (${foreignSource}) → must execute on Databricks`);
      await emit("decision", "rules", `Mandatory rule matched — skipping remaining rules`);
      engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "mandatory_rule"; reason = `Foreign table (${foreignSource}) — must route via Databricks`; execTime = 450; complexity = 10;
    } else if (sqlLower.includes("revenue_summary")) {
      await emit("rule", "rules", `Rule #SYS-1 [mandatory]: table=revenue_summary is a VIEW → must execute on Databricks`);
      await emit("decision", "rules", `Mandatory rule matched — skipping remaining rules`);
      engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "mandatory_rule"; reason = "VIEW — must execute on Databricks"; execTime = 340; complexity = 25;
    } else if (sqlLower.includes("customer_pii")) {
      await emit("rule", "rules", `Rule #SYS-2 [mandatory]: table=customer_pii has row-level security → must execute on Databricks`);
      await emit("decision", "rules", `Mandatory rule matched — skipping remaining rules`);
      engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "mandatory_rule"; reason = "Has row-level security filter — must execute on Databricks"; execTime = 280; complexity = 18;
    } else if (sqlLower.includes("store_sales")) {
      await emit("info", "rules", `Rule #SYS-1 [mandatory]: no match (not a VIEW)`);
      await emit("info", "rules", `Rule #SYS-2 [mandatory]: no match (no RLS filter)`);
      await emit("rule", "rules", `Rule #USR-1 [user]: table_name contains "store_sales" → route to DuckDB`);
      await emit("decision", "rules", `User rule matched — skipping ML model evaluation`);
      engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "user_rule"; reason = "User rule: table_name = store_sales → DuckDB"; execTime = 120; complexity = 15;
    } else {
      await emit("info", "rules", `Rule #SYS-1 [mandatory]: no match`);
      await emit("info", "rules", `Rule #SYS-2 [mandatory]: no match`);
      await emit("info", "rules", `Rule #USR-1 [user]: no match`);
      await emit("info", "rules", `No rules matched — proceeding to ML model`);

      if (routingMode === "duckdb") {
        engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "fallback"; reason = "Routing mode forced to DuckDB"; execTime = 85; complexity = 12;
      } else if (routingMode === "databricks") {
        engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "fallback"; reason = "Routing mode forced to Databricks"; execTime = 250; complexity = 12;
      } else {
        engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "fallback"; reason = "Query complexity low, no governance constraints, estimated 45ms on DuckDB vs 230ms on Databricks"; execTime = 85; complexity = 12;
      }

      // --- Phase 3: ML Model ---
      await emit("info", "ml_model", `Evaluating ML model prediction...`, 120 + Math.random() * 100);
      await emit("info", "ml_model", `Complexity score: ${complexity}`);
      if (routingMode !== "smart") {
        await emit("warn", "ml_model", `Routing mode forced to "${routingMode}" — ML prediction overridden`);
      } else {
        await emit("info", "ml_model", `Predicted latency: DuckDB=${execTime}ms, Databricks=230ms`);
      }
    }

    // --- Phase 3.5: Running Engine Bonus ---
    const selectedIsRunning = engine.startsWith("duckdb"); // DuckDB engines are always running in mock
    const bonusType = engine.startsWith("duckdb") ? "DuckDB" : "Databricks";
    const bonusValue = engine.startsWith("duckdb") ? routingSettings.running_bonus_duckdb : routingSettings.running_bonus_databricks;
    await emit("info", "bonus", `Evaluating running engine bonus...`, 60);
    if (selectedIsRunning && bonusValue > 0) {
      await emit("info", "bonus", `Engine ${engineName} is RUNNING — applying ${bonusType} bonus (−${bonusValue.toFixed(2)} to score)`);
    } else if (!selectedIsRunning) {
      await emit("info", "bonus", `Engine ${engineName} is STOPPED — no bonus applied`);
    } else {
      await emit("info", "bonus", `${bonusType} bonus is 0 — no adjustment`);
    }

    // --- Phase 4: Engine selection ---
    await emit("decision", "engine", `Selected engine: ${engineName}`, 60);
    await emit("info", "engine", `Routing stage: ${stage.replace(/_/g, " ")}`, 40);
    await emit("info", "engine", `Reason: ${reason}`, 30);

    // --- Phase 5: Execution ---
    await emit("info", "execute", `Submitting query to ${engineName}...`, 80);
    // Simulate actual execution time (scaled down for UI)
    const simExecDelay = 200 + Math.random() * 300;
    await emit("info", "execute", `Waiting for engine response...`, simExecDelay);

    // Build result data
    let columns: string[];
    let rows: any[][];

    if (sqlLower.includes("customer") && !sqlLower.includes("customer_pii") && !sqlLower.includes("customer_demographics")) {
      columns = ["c_customer_sk", "c_first_name", "c_last_name"];
      const names = [["John", "Smith"], ["Jane", "Doe"], ["Bob", "Wilson"], ["Alice", "Brown"], ["Charlie", "Davis"], ["Diana", "Miller"], ["Eve", "Taylor"], ["Frank", "Anderson"], ["Grace", "Thomas"], ["Henry", "Jackson"]];
      rows = names.map((n, i) => [i + 1, n[0], n[1]]);
    } else {
      columns = ["col_1", "col_2", "col_3", "col_4"];
      rows = [];
      for (let i = 0; i < 10; i++) {
        rows.push([i + 1, `value_${i}`, Math.floor(Math.random() * 1000), `data_${String.fromCharCode(65 + i)}`]);
      }
    }

    await emit("info", "complete", `Query executed in ${execTime}ms, ${rows.length} rows returned`, 40);

    const ioLatency = engine.startsWith("duckdb") ? 8 + Math.random() * 15 : undefined;
    const coldStart = 0; // engines assumed warm during normal execution
    const computeTime = ioLatency != null ? execTime - ioLatency : undefined;

    const routingDecision: QueryExecutionResult["routing_decision"] = {
      engine, engine_display_name: engineName, stage, reason, complexity_score: complexity,
      compute_time_ms: computeTime != null ? Math.round(computeTime) : undefined,
      io_latency_ms: ioLatency != null ? Math.round(ioLatency) : undefined,
      cold_start_ms: coldStart,
      total_latency_ms: execTime,
    };

    // Update the running entry with final results
    runningEntry.engine = engine;
    runningEntry.engine_display_name = engineName;
    runningEntry.status = "success";
    runningEntry.latency_ms = execTime;
    runningEntry.routing_decision = routingDecision;
    runningEntry.routing_events = [...collectedEvents]; // snapshot

    return {
      correlation_id: correlationId,
      routing_decision: routingDecision,
      execution: { execution_time_ms: execTime, data_scanned_bytes: 1200000 },
      columns, rows,
    };
  },

  // Benchmarks
  async getBenchmarks(collectionId?: number): Promise<BenchmarkSummary[]> {
    // TODO: Replace with real API call — GET /api/benchmarks
    await delay(200);
    const filtered = collectionId != null ? benchmarks.filter(b => b.collection_id === collectionId) : benchmarks;
    return filtered.map(({ warmups: _w, results: _r, storage_probes: _s, ...rest }) => rest);
  },

  async getBenchmark(id: number): Promise<BenchmarkDetail> {
    // TODO: Replace with real API call — GET /api/benchmarks/:id
    await delay(300);
    const b = benchmarks.find(b => b.id === id);
    if (!b) throw new Error("Not found");
    return JSON.parse(JSON.stringify(b));
  },

  async createBenchmark(collectionId: number, _catalogEngineIds: number[]): Promise<BenchmarkSummary> {
    // TODO: Replace with real API call — POST /api/benchmarks
    await delay(500);
    const b: BenchmarkDetail = {
      id: nextBenchmarkId++, collection_id: collectionId, status: "complete", engine_count: 3,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      warmups: [
        { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", cold_start_time_ms: 115, started_at: new Date().toISOString() },
        { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", cold_start_time_ms: 2350, started_at: new Date().toISOString() },
      ],
      results: [
        { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 1, execution_time_ms: 42, data_scanned_bytes: 1200000 },
        { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 1, execution_time_ms: 185, data_scanned_bytes: 1200000 },
      ],
    };
    benchmarks.push(b);
    const { warmups: _w, results: _r, storage_probes: _s, ...rest } = b;
    return rest;
  },

  async deleteBenchmark(id: number): Promise<void> {
    // TODO: Replace with real API call — DELETE /api/benchmarks/:id
    await delay(200);
    benchmarks = benchmarks.filter(b => b.id !== id);
  },

  // Routing Rules
  async getRoutingRules(): Promise<RoutingRule[]> {
    // TODO: Replace with real API call — GET /api/routing/rules
    await delay(200);
    return JSON.parse(JSON.stringify(routingRules));
  },

  async createRoutingRule(rule: Omit<RoutingRule, "id">): Promise<RoutingRule> {
    // TODO: Replace with real API call — POST /api/routing/rules
    await delay(200);
    const r: RoutingRule = { ...rule, id: nextRuleId++ };
    routingRules.push(r);
    return { ...r };
  },

  async updateRoutingRule(id: number, data: Partial<RoutingRule>): Promise<RoutingRule> {
    // TODO: Replace with real API call — PUT /api/routing/rules/:id
    await delay(200);
    const r = routingRules.find(r => r.id === id);
    if (!r) throw new Error("Not found");
    Object.assign(r, data);
    return { ...r };
  },

  async deleteRoutingRule(id: number): Promise<void> {
    // TODO: Replace with real API call — DELETE /api/routing/rules/:id
    await delay(200);
    routingRules = routingRules.filter(r => r.id !== id);
  },

  async toggleRoutingRule(id: number, enabled: boolean): Promise<RoutingRule> {
    // TODO: Replace with real API call — PUT /api/routing/rules/:id/toggle
    await delay(200);
    const r = routingRules.find(r => r.id === id);
    if (!r) throw new Error("Not found");
    r.enabled = enabled;
    return { ...r };
  },

  async resetRoutingRules(): Promise<RoutingRule[]> {
    // TODO: Replace with real API call — POST /api/routing/rules/reset
    await delay(300);
    routingRules = [
      { id: 1, priority: 1, condition_type: "table_type", condition_value: "VIEW", target_engine: "databricks", is_system: true, enabled: true },
      { id: 2, priority: 2, condition_type: "has_governance", condition_value: "row_filter", target_engine: "databricks", is_system: true, enabled: true },
    ];
    return JSON.parse(JSON.stringify(routingRules));
  },

  // Models
  async getModels(): Promise<Model[]> {
    // TODO: Replace with real API call — GET /api/models
    await delay(200);
    return JSON.parse(JSON.stringify(models));
  },

  async trainModel(enabledEngineIds: string[], _trainingConfig?: { collections?: { id: number; runs: number }[]; benchmarkIds?: number[] }): Promise<Model> {
    // TODO: Replace with real API call — POST /api/models/train
    await delay(3000);
    const benchmarkCount = (_trainingConfig?.benchmarkIds?.length ?? 0) +
      (_trainingConfig?.collections?.reduce((sum, c) => sum + c.runs, 0) ?? 1);
    const m: Model = {
      id: nextModelId++, linked_engines: [...enabledEngineIds],
      latency_model: {
        r_squared: 0.82 + Math.random() * 0.1,
        mae_ms: 30 + Math.floor(Math.random() * 30),
        model_path: `/models/bundle_${String(nextModelId - 1).padStart(3, "0")}_latency.joblib`,
      },
      cost_model: {
        r_squared: 0.80 + Math.random() * 0.12,
        mae_usd: 0.001 + Math.random() * 0.002,
        model_path: `/models/bundle_${String(nextModelId - 1).padStart(3, "0")}_cost.joblib`,
      },
      is_active: false, created_at: new Date().toISOString(),
      benchmark_count: benchmarkCount,
      training_queries: benchmarkCount * 5,
    };
    models.push(m);
    return JSON.parse(JSON.stringify(m));
  },

  async activateModel(id: number): Promise<Model> {
    // TODO: Replace with real API call — POST /api/models/:id/activate
    await delay(200);
    models.forEach(m => m.is_active = m.id === id);
    const m = models.find(m => m.id === id)!;
    return JSON.parse(JSON.stringify(m));
  },

  async deactivateModel(id: number): Promise<Model> {
    // TODO: Replace with real API call — POST /api/models/:id/deactivate
    await delay(200);
    const m = models.find(m => m.id === id);
    if (!m) throw new Error("Not found");
    m.is_active = false;
    return JSON.parse(JSON.stringify(m));
  },

  async deleteModel(id: number): Promise<void> {
    // TODO: Replace with real API call — DELETE /api/models/:id
    await delay(200);
    models = models.filter(m => m.id !== id);
  },

  // Query Log
  async getQueryLogs(engineFilter?: string): Promise<LogEntry[]> {
    // TODO: Replace with real API call — GET /api/query/logs
    await delay(200);
    let logs = [...queryLogs];
    if (engineFilter && engineFilter !== "all") {
      logs = logs.filter(l => l.engine.startsWith(engineFilter));
    }
    return logs.slice(0, 20);
  },

  // Utility: count benchmark runs for given engines
  async getBenchmarkCountForEngines(engineIds: string[]): Promise<number> {
    // TODO: Replace with real API call — GET /api/benchmarks/count
    await delay(100);
    // Count unique benchmark results that involve any of the given engine IDs
    let count = 0;
    for (const b of benchmarks) {
      const hasEngine = b.results.some(r => engineIds.includes(r.engine_id));
      if (hasEngine) count += b.results.filter(r => engineIds.includes(r.engine_id)).length;
    }
    return count;
  },

  // Storage Latency Probes (ODQ-9)
  async getStorageLatencyProbes(): Promise<StorageLatencyProbe[]> {
    // TODO: Replace with real API call — GET /api/storage/probes
    await delay(200);
    return JSON.parse(JSON.stringify(storageLatencyProbes));
  },

  async runStorageLatencyProbes(): Promise<StorageLatencyProbe[]> {
    // TODO: Replace with real API call — POST /api/storage/probes/run
    await delay(2000); // Simulate probe execution time
    const now = new Date().toISOString();
    const newProbes: StorageLatencyProbe[] = [
      { id: storageLatencyProbes.length + 1, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 11.5 + Math.random() * 3, bytes_read: 1048576, measured_at: now },
      { id: storageLatencyProbes.length + 2, storage_location: "s3://delta-router/tpcds/", engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", probe_time_ms: 10.2 + Math.random() * 3, bytes_read: 1048576, measured_at: now },
      { id: storageLatencyProbes.length + 3, storage_location: "s3://delta-router/analytics/", engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", probe_time_ms: 13.0 + Math.random() * 3, bytes_read: 1048576, measured_at: now },
    ];
    storageLatencyProbes.push(...newProbes);
    return JSON.parse(JSON.stringify(newProbes));
  },

  // Routing Settings
  async getRoutingSettings(): Promise<RoutingSettings> {
    // TODO: Replace with real API call — GET /api/routing/settings
    await delay(100);
    return { ...routingSettings };
  },

  async updateRoutingSettings(settings: Partial<RoutingSettings>): Promise<RoutingSettings> {
    // TODO: Replace with real API call — PUT /api/routing/settings
    await delay(200);
    Object.assign(routingSettings, settings);
    return { ...routingSettings };
  },
};
