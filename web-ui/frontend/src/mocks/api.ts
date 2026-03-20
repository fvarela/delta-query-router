import type {
  Workspace, DatabricksSettings, DatabricksCredentials, DatabricksConnectResponse,
  Warehouse, Collection, CollectionWithQueries, Query,
  EngineCatalogEntry, EnginePreference, RoutingRule, RoutingSettings,
  QueryExecutionResult, BenchmarkSummary, BenchmarkDetail,
  Model, CatalogInfo, SchemaInfo, TableInfo, LogEntry,
  RoutingLogEvent, RoutingLogLevel,
} from "../types";

const delay = (ms: number) => new Promise(r => setTimeout(r, ms));

const logTs = () => {
  const d = new Date();
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}.${d.getMilliseconds().toString().padStart(3, "0")}`;
};

const mkLog = (level: RoutingLogLevel, stage: string, message: string): RoutingLogEvent => ({
  timestamp: logTs(), level, stage, message,
});

// ---- Mutable state ----
let connectedWorkspaceId: string | null = null;
let selectedWarehouseId: string | null = null;
let nextCollectionId = 3;
let nextQueryId = 100;
let nextRuleId = 100;
let nextModelId = 3;
let nextBenchmarkId = 2;
let nextWorkspaceId = 3;

let workspaces: Workspace[] = [
  { id: "ws-1", name: "Production", url: "https://adb-1234567890.12.azuredatabricks.net", token: null, connected: false },
  { id: "ws-2", name: "Development", url: "https://adb-9876543210.34.azuredatabricks.net", token: null, connected: false },
];

let engineCatalog: EngineCatalogEntry[] = [
  { id: 1, engine_type: "databricks_sql", display_name: "Serverless 2X-Small", config: { cluster_size: "2XS" }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
  { id: 2, engine_type: "databricks_sql", display_name: "Serverless Medium", config: { cluster_size: "M" }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
  { id: 3, engine_type: "databricks_sql", display_name: "Serverless Large", config: { cluster_size: "L" }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
  { id: 4, engine_type: "duckdb", display_name: "DuckDB 2GB/2CPU", config: { memory_gb: 2, cpu_count: 2 }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
  { id: 5, engine_type: "duckdb", display_name: "DuckDB 8GB/4CPU", config: { memory_gb: 8, cpu_count: 4 }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
  { id: 6, engine_type: "duckdb", display_name: "DuckDB 16GB/8CPU", config: { memory_gb: 16, cpu_count: 8 }, is_default: true, enabled: true, created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" },
];
const defaultEngineCatalog = JSON.parse(JSON.stringify(engineCatalog));

let routingRules: RoutingRule[] = [
  { id: 1, priority: 1, condition_type: "table_type", condition_value: "VIEW", target_engine: "databricks", is_system: true, enabled: true },
  { id: 2, priority: 2, condition_type: "has_governance", condition_value: "row_filter", target_engine: "databricks", is_system: true, enabled: true },
  { id: 3, priority: 10, condition_type: "table_name", condition_value: "store_sales", target_engine: "duckdb", is_system: false, enabled: true },
];

let routingSettings: RoutingSettings = { time_weight: 0.5, cost_weight: 0.5 };

let models: Model[] = [
  { id: 1, linked_engines: ["duckdb:2gb-2cpu", "databricks:serverless-2xs", "duckdb:8gb-4cpu"], model_path: "/models/model_001.joblib", accuracy_metrics: { r_squared: 0.87, mae_ms: 45 }, is_active: false, created_at: "2026-03-10T14:30:00Z", benchmark_count: 12 },
  { id: 2, linked_engines: ["duckdb:2gb-2cpu", "duckdb:8gb-4cpu"], model_path: "/models/model_002.joblib", accuracy_metrics: { r_squared: 0.79, mae_ms: 62 }, is_active: false, created_at: "2026-03-12T10:00:00Z", benchmark_count: 8 },
];

let collections: CollectionWithQueries[] = [
  {
    id: 1, name: "TPC-DS Benchmark", description: "Standard TPC-DS queries for benchmarking", created_at: "2026-03-10T10:00:00Z", updated_at: "2026-03-14T15:00:00Z",
    queries: [
      { id: 1, collection_id: 1, query_text: "SELECT c_customer_sk, c_first_name, c_last_name FROM delta_router_dev.tpcds.customer WHERE c_birth_country = 'UNITED STATES' LIMIT 100", sequence_number: 1 },
      { id: 2, collection_id: 1, query_text: "SELECT ss_sold_date_sk, SUM(ss_net_profit) AS total_profit FROM delta_router_dev.tpcds.store_sales GROUP BY ss_sold_date_sk ORDER BY total_profit DESC LIMIT 20", sequence_number: 2 },
      { id: 3, collection_id: 1, query_text: "SELECT cs_sold_date_sk, cs_item_sk, cs_quantity FROM delta_router_dev.tpcds.catalog_sales WHERE cs_quantity > 50 LIMIT 100", sequence_number: 3 },
      { id: 4, collection_id: 1, query_text: "SELECT cd_gender, cd_education_status, COUNT(*) AS cnt FROM delta_router_dev.tpcds.customer_demographics GROUP BY cd_gender, cd_education_status", sequence_number: 4 },
      { id: 5, collection_id: 1, query_text: "SELECT d_date_sk, d_year, d_quarter_name FROM delta_router_dev.tpcds.date_dim WHERE d_year = 2024", sequence_number: 5 },
    ],
  },
  {
    id: 2, name: "Ad-hoc Queries", description: "Quick exploratory queries", created_at: "2026-03-12T08:00:00Z", updated_at: "2026-03-14T12:00:00Z",
    queries: [
      { id: 6, collection_id: 2, query_text: "SELECT * FROM delta_router_dev.analytics.revenue_summary LIMIT 50", sequence_number: 1 },
      { id: 7, collection_id: 2, query_text: "SELECT * FROM delta_router_dev.tpcds.customer WHERE c_customer_sk < 100", sequence_number: 2 },
    ],
  },
];

let queryLogs: LogEntry[] = [
  { correlation_id: "log-1", timestamp: "2026-03-15 10:45:12", query_text: "SELECT c_customer_sk, c_first_name, c_last_name FROM delta_router_dev.tpcds.customer WHERE c_birth_country = 'UNITED STATES' LIMIT 100", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 45, cost_usd: 0.0003 },
  { correlation_id: "log-2", timestamp: "2026-03-15 10:44:30", query_text: "SELECT ss_sold_date_sk, SUM(ss_net_profit) AS total_profit FROM delta_router_dev.tpcds.store_sales GROUP BY ss_sold_date_sk ORDER BY total_profit DESC LIMIT 20", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 890, cost_usd: 0.0025 },
  { correlation_id: "log-3", timestamp: "2026-03-15 10:43:15", query_text: "SELECT * FROM delta_router_dev.analytics.revenue_summary LIMIT 50", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "success", latency_ms: 340, cost_usd: 0.015 },
  { correlation_id: "log-4", timestamp: "2026-03-15 10:42:00", query_text: "SELECT cd_gender, cd_education_status, COUNT(*) AS cnt FROM delta_router_dev.tpcds.customer_demographics GROUP BY cd_gender, cd_education_status", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 65, cost_usd: 0.0004 },
  { correlation_id: "log-5", timestamp: "2026-03-15 10:40:45", query_text: "SELECT * FROM delta_router_dev.tpcds.customer_pii LIMIT 100", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "success", latency_ms: 280, cost_usd: 0.0095 },
  { correlation_id: "log-6", timestamp: "2026-03-15 10:39:30", query_text: "SELECT d_date_sk, d_year FROM delta_router_dev.tpcds.date_dim WHERE d_year = 2024", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 30, cost_usd: 0.0002 },
  { correlation_id: "log-7", timestamp: "2026-03-15 10:38:00", query_text: "SELECT cs_sold_date_sk, cs_item_sk, cs_quantity FROM delta_router_dev.tpcds.catalog_sales WHERE cs_quantity > 50 LIMIT 100", engine: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", status: "success", latency_ms: 620, cost_usd: 0.0018 },
  { correlation_id: "log-8", timestamp: "2026-03-15 10:36:45", query_text: "INSERT INTO delta_router_dev.tpcds.customer VALUES (...)", engine: "databricks:serverless-2xs", engine_display_name: "Databricks 2X-Small", status: "error", latency_ms: 150, cost_usd: 0 },
  { correlation_id: "log-9", timestamp: "2026-03-15 10:35:30", query_text: "SELECT COUNT(*) FROM delta_router_dev.tpcds.store_sales", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 22, cost_usd: 0.0001 },
  { correlation_id: "log-10", timestamp: "2026-03-15 10:34:00", query_text: "SELECT * FROM delta_router_dev.tpcds.customer WHERE c_customer_sk = 1", engine: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", status: "success", latency_ms: 55, cost_usd: 0.0003 },
];

let benchmarks: BenchmarkDetail[] = [
  {
    id: 1, collection_id: 1, status: "complete", engine_count: 3, created_at: "2026-03-14T09:00:00Z", updated_at: "2026-03-14T09:05:00Z",
    warmups: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", cold_start_time_ms: 120, started_at: "2026-03-14T09:00:00Z" },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", cold_start_time_ms: 2400, started_at: "2026-03-14T09:00:00Z" },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", cold_start_time_ms: 180, started_at: "2026-03-14T09:00:00Z" },
    ],
    results: [
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 1, execution_time_ms: 45, data_scanned_bytes: 1200000 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 1, execution_time_ms: 180, data_scanned_bytes: 1200000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 1, execution_time_ms: 38, data_scanned_bytes: 1200000 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 2, execution_time_ms: 890, data_scanned_bytes: 52000000 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 2, execution_time_ms: 320, data_scanned_bytes: 52000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 2, execution_time_ms: 450, data_scanned_bytes: 52000000 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 3, execution_time_ms: 1200, data_scanned_bytes: 85000000 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 3, execution_time_ms: 410, data_scanned_bytes: 85000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 3, execution_time_ms: 620, data_scanned_bytes: 85000000 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 4, execution_time_ms: 65, data_scanned_bytes: 3000000 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 4, execution_time_ms: 195, data_scanned_bytes: 3000000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 4, execution_time_ms: 52, data_scanned_bytes: 3000000 },
      { engine_id: "duckdb:2gb-2cpu", engine_display_name: "DuckDB 2GB/2CPU", query_id: 5, execution_time_ms: 30, data_scanned_bytes: 800000 },
      { engine_id: "databricks:serverless-2xs", engine_display_name: "Serverless 2X-Small", query_id: 5, execution_time_ms: 160, data_scanned_bytes: 800000 },
      { engine_id: "duckdb:8gb-4cpu", engine_display_name: "DuckDB 8GB/4CPU", query_id: 5, execution_time_ms: 25, data_scanned_bytes: 800000 },
    ],
  },
];

// ---- Table data ----
const tableData: Record<string, TableInfo[]> = {
  "delta_router_dev.tpcds": [
    { name: "customer", full_name: "delta_router_dev.tpcds.customer", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 47185920, row_count: 100000, storage_location: "s3://delta-router/tpcds/customer", external_engine_read_support: true, columns: [{ name: "c_customer_sk", type_text: "INT" }, { name: "c_customer_id", type_text: "STRING" }, { name: "c_first_name", type_text: "STRING" }, { name: "c_last_name", type_text: "STRING" }, { name: "c_birth_country", type_text: "STRING" }, { name: "c_email_address", type_text: "STRING" }] },
    { name: "store_sales", full_name: "delta_router_dev.tpcds.store_sales", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 2254857830, row_count: 28000000, storage_location: "s3://delta-router/tpcds/store_sales", external_engine_read_support: true, columns: [{ name: "ss_sold_date_sk", type_text: "INT" }, { name: "ss_item_sk", type_text: "INT" }, { name: "ss_customer_sk", type_text: "INT" }, { name: "ss_net_profit", type_text: "DECIMAL(7,2)" }, { name: "ss_quantity", type_text: "INT" }] },
    { name: "catalog_sales", full_name: "delta_router_dev.tpcds.catalog_sales", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 3650722202, row_count: 43000000, storage_location: "s3://delta-router/tpcds/catalog_sales", external_engine_read_support: true, columns: [{ name: "cs_sold_date_sk", type_text: "INT" }, { name: "cs_item_sk", type_text: "INT" }, { name: "cs_quantity", type_text: "INT" }, { name: "cs_net_profit", type_text: "DECIMAL(7,2)" }] },
    { name: "customer_demographics", full_name: "delta_router_dev.tpcds.customer_demographics", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 12582912, row_count: 1920000, storage_location: "s3://delta-router/tpcds/customer_demographics", external_engine_read_support: true, columns: [{ name: "cd_demo_sk", type_text: "INT" }, { name: "cd_gender", type_text: "STRING" }, { name: "cd_education_status", type_text: "STRING" }, { name: "cd_credit_rating", type_text: "STRING" }] },
    { name: "date_dim", full_name: "delta_router_dev.tpcds.date_dim", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 5242880, row_count: 73049, storage_location: "s3://delta-router/tpcds/date_dim", external_engine_read_support: true, columns: [{ name: "d_date_sk", type_text: "INT" }, { name: "d_date_id", type_text: "STRING" }, { name: "d_year", type_text: "INT" }, { name: "d_quarter_name", type_text: "STRING" }, { name: "d_month_seq", type_text: "INT" }] },
  ],
  "delta_router_dev.analytics": [
    { name: "revenue_summary", full_name: "delta_router_dev.analytics.revenue_summary", table_type: "VIEW", data_source_format: null, size_bytes: null, row_count: null, storage_location: null, external_engine_read_support: false, read_support_reason: "View — must execute on Databricks", columns: [{ name: "year", type_text: "INT" }, { name: "quarter", type_text: "STRING" }, { name: "total_revenue", type_text: "DECIMAL(12,2)" }, { name: "total_cost", type_text: "DECIMAL(12,2)" }] },
    { name: "customer_pii", full_name: "delta_router_dev.analytics.customer_pii", table_type: "MANAGED", data_source_format: "DELTA", size_bytes: 241172480, row_count: 1000000, storage_location: "s3://delta-router/analytics/customer_pii", external_engine_read_support: false, read_support_reason: "Has row-level security filter", columns: [{ name: "customer_id", type_text: "INT" }, { name: "ssn", type_text: "STRING" }, { name: "full_name", type_text: "STRING" }, { name: "email", type_text: "STRING" }, { name: "phone", type_text: "STRING" }] },
  ],
};

// ---- Mock API ----
export const mockApi = {
  // Workspaces
  async getWorkspaces(): Promise<Workspace[]> {
    await delay(200);
    return JSON.parse(JSON.stringify(workspaces));
  },

  async addWorkspace(name: string, url: string): Promise<Workspace> {
    await delay(200);
    const ws: Workspace = { id: `ws-${nextWorkspaceId++}`, name, url, token: null, connected: false };
    workspaces.push(ws);
    return { ...ws };
  },

  async deleteWorkspace(id: string): Promise<void> {
    await delay(200);
    if (connectedWorkspaceId === id) connectedWorkspaceId = null;
    workspaces = workspaces.filter(w => w.id !== id);
  },

  async setWorkspaceToken(id: string, token: string): Promise<Workspace> {
    await delay(200);
    const ws = workspaces.find(w => w.id === id);
    if (!ws) throw new Error("Workspace not found");
    ws.token = token;
    return { ...ws };
  },

  async connectWorkspace(id: string): Promise<Workspace> {
    await delay(600);
    // Disconnect any existing
    workspaces.forEach(w => w.connected = false);
    const ws = workspaces.find(w => w.id === id);
    if (!ws) throw new Error("Workspace not found");
    if (!ws.token) throw new Error("No PAT token configured");
    ws.connected = true;
    connectedWorkspaceId = id;
    return { ...ws };
  },

  async disconnectWorkspace(id: string): Promise<Workspace> {
    await delay(200);
    const ws = workspaces.find(w => w.id === id);
    if (!ws) throw new Error("Workspace not found");
    ws.connected = false;
    if (connectedWorkspaceId === id) connectedWorkspaceId = null;
    return { ...ws };
  },

  // Catalog browser
  async getCatalogs(): Promise<CatalogInfo[]> {
    await delay(300);
    return [{ name: "delta_router_dev" }];
  },

  async getSchemas(_catalog: string): Promise<SchemaInfo[]> {
    await delay(300);
    return [
      { name: "tpcds", catalog_name: "delta_router_dev" },
      { name: "analytics", catalog_name: "delta_router_dev" },
    ];
  },

  async getTables(catalog: string, schema: string): Promise<TableInfo[]> {
    await delay(400);
    return tableData[`${catalog}.${schema}`] || [];
  },

  // Collections
  async getCollections(): Promise<Collection[]> {
    await delay(200);
    return collections.map(({ queries: _q, ...c }) => c);
  },

  async getCollection(id: number): Promise<CollectionWithQueries> {
    await delay(200);
    const c = collections.find(c => c.id === id);
    if (!c) throw new Error("Collection not found");
    return JSON.parse(JSON.stringify(c));
  },

  async createCollection(name: string, description: string): Promise<Collection> {
    await delay(300);
    const c: CollectionWithQueries = { id: nextCollectionId++, name, description, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), queries: [] };
    collections.push(c);
    const { queries: _q, ...rest } = c;
    return rest;
  },

  async updateCollection(id: number, data: Partial<Collection>): Promise<Collection> {
    await delay(200);
    const c = collections.find(c => c.id === id);
    if (!c) throw new Error("Not found");
    Object.assign(c, data, { updated_at: new Date().toISOString() });
    const { queries: _q, ...rest } = c;
    return rest;
  },

  async deleteCollection(id: number): Promise<void> {
    await delay(200);
    collections = collections.filter(c => c.id !== id);
  },

  async addQuery(collectionId: number, queryText: string): Promise<Query> {
    await delay(200);
    const c = collections.find(c => c.id === collectionId);
    if (!c) throw new Error("Not found");
    const seq = c.queries.length + 1;
    const q: Query = { id: nextQueryId++, collection_id: collectionId, query_text: queryText, sequence_number: seq };
    c.queries.push(q);
    return q;
  },

  async deleteQuery(collectionId: number, queryId: number): Promise<void> {
    await delay(200);
    const c = collections.find(c => c.id === collectionId);
    if (!c) throw new Error("Not found");
    c.queries = c.queries.filter(q => q.id !== queryId);
    c.queries.forEach((q, i) => q.sequence_number = i + 1);
  },

  // Query Execution
  async executeQuery(sql: string, routingMode: string, onLog?: (event: RoutingLogEvent) => void): Promise<QueryExecutionResult> {
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
      cost_usd: 0,
      routing_events: collectedEvents, // live reference — grows as events stream
    };
    queryLogs.unshift(runningEntry);

    // --- Phase 1: Parse ---
    await emit("info", "parse", `Received query (${sql.length} chars), correlation_id=${correlationId}`, 50);
    await emit("info", "parse", `Parsing SQL statement...`, 100 + Math.random() * 100);

    // Detect tables referenced
    const tableHints: string[] = [];
    for (const t of ["revenue_summary", "customer_pii", "customer_demographics", "store_sales", "customer", "catalog_sales", "date_dim"]) {
      if (sqlLower.includes(t)) tableHints.push(t);
    }
    await emit("info", "parse", `Tables referenced: ${tableHints.length > 0 ? tableHints.join(", ") : "(inline/unknown)"}`, 60);

    // Detect statement type
    const stmtType = sqlLower.trimStart().startsWith("select") ? "SELECT" : sqlLower.trimStart().startsWith("insert") ? "INSERT" : "OTHER";
    await emit("info", "parse", `Statement type: ${stmtType}`, 40);

    // --- Phase 2: Routing rules ---
    let engine: string, engineName: string, stage: "mandatory_rule" | "user_rule" | "ml_prediction" | "fallback", reason: string, execTime: number, cost: number, savings: number, complexity: number;

    await emit("info", "rules", `Evaluating routing rules...`, 100 + Math.random() * 80);

    if (sqlLower.includes("revenue_summary")) {
      await emit("rule", "rules", `Rule #SYS-1 [mandatory]: table=revenue_summary is a VIEW → must execute on Databricks`);
      await emit("decision", "rules", `Mandatory rule matched — skipping remaining rules`);
      engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "mandatory_rule"; reason = "VIEW — must execute on Databricks"; execTime = 340; cost = 0.015; savings = 0; complexity = 25;
    } else if (sqlLower.includes("customer_pii")) {
      await emit("rule", "rules", `Rule #SYS-2 [mandatory]: table=customer_pii has row-level security → must execute on Databricks`);
      await emit("decision", "rules", `Mandatory rule matched — skipping remaining rules`);
      engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "mandatory_rule"; reason = "Has row-level security filter — must execute on Databricks"; execTime = 280; cost = 0.0095; savings = 0; complexity = 18;
    } else if (sqlLower.includes("store_sales")) {
      await emit("info", "rules", `Rule #SYS-1 [mandatory]: no match (not a VIEW)`);
      await emit("info", "rules", `Rule #SYS-2 [mandatory]: no match (no RLS filter)`);
      await emit("rule", "rules", `Rule #USR-1 [user]: table_name contains "store_sales" → route to DuckDB`);
      await emit("decision", "rules", `User rule matched — skipping ML model evaluation`);
      engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "user_rule"; reason = "User rule: table_name = store_sales → DuckDB"; execTime = 120; cost = 0.0008; savings = 0.012; complexity = 15;
    } else {
      await emit("info", "rules", `Rule #SYS-1 [mandatory]: no match`);
      await emit("info", "rules", `Rule #SYS-2 [mandatory]: no match`);
      await emit("info", "rules", `Rule #USR-1 [user]: no match`);
      await emit("info", "rules", `No rules matched — proceeding to ML model`);

      if (routingMode === "duckdb") {
        engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "fallback"; reason = "Routing mode forced to DuckDB"; execTime = 85; cost = 0.0003; savings = 0.0045; complexity = 12;
      } else if (routingMode === "databricks") {
        engine = "databricks:serverless-2xs"; engineName = "Databricks Serverless 2X-Small"; stage = "fallback"; reason = "Routing mode forced to Databricks"; execTime = 250; cost = 0.012; savings = 0; complexity = 12;
      } else {
        engine = "duckdb:2gb-2cpu"; engineName = "DuckDB 2GB/2CPU"; stage = "fallback"; reason = "Query complexity low, no governance constraints, estimated 45ms on DuckDB vs 230ms on Databricks"; execTime = 85; cost = 0.0003; savings = 0.0045; complexity = 12;
      }

      // --- Phase 3: ML Model ---
      await emit("info", "ml_model", `Evaluating ML model prediction...`, 120 + Math.random() * 100);
      await emit("info", "ml_model", `Complexity score: ${complexity}`);
      if (routingMode !== "smart") {
        await emit("warn", "ml_model", `Routing mode forced to "${routingMode}" — ML prediction overridden`);
      } else {
        await emit("info", "ml_model", `Predicted latency: DuckDB=${execTime}ms, Databricks=230ms`);
        await emit("info", "ml_model", `Predicted cost: DuckDB=$${cost.toFixed(4)}, Databricks=$0.0120`);
      }
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
    await emit("info", "complete", `Cost: $${cost.toFixed(4)}${savings > 0 ? `, savings: $${savings.toFixed(4)}` : ""}`, 30);
    if (savings > 0) {
      await emit("info", "complete", `Estimated savings by routing to ${engineName} instead of Databricks`, 20);
    }

    const routingDecision = { engine, engine_display_name: engineName, stage, reason, complexity_score: complexity };

    // Update the running entry with final results
    runningEntry.engine = engine;
    runningEntry.engine_display_name = engineName;
    runningEntry.status = "success";
    runningEntry.latency_ms = execTime;
    runningEntry.cost_usd = cost;
    runningEntry.routing_decision = routingDecision;
    runningEntry.routing_events = [...collectedEvents]; // snapshot

    return {
      correlation_id: correlationId,
      routing_decision: routingDecision,
      execution: { execution_time_ms: execTime, data_scanned_bytes: 1200000, estimated_cost_usd: cost, cost_savings_usd: savings },
      columns, rows,
    };
  },

  // Benchmarks
  async getBenchmarks(collectionId: number): Promise<BenchmarkSummary[]> {
    await delay(200);
    return benchmarks.filter(b => b.collection_id === collectionId).map(({ warmups: _w, results: _r, ...rest }) => rest);
  },

  async getBenchmark(id: number): Promise<BenchmarkDetail> {
    await delay(300);
    const b = benchmarks.find(b => b.id === id);
    if (!b) throw new Error("Not found");
    return JSON.parse(JSON.stringify(b));
  },

  async createBenchmark(collectionId: number, _catalogEngineIds: number[]): Promise<BenchmarkSummary> {
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
    const { warmups: _w, results: _r, ...rest } = b;
    return rest;
  },

  async deleteBenchmark(id: number): Promise<void> {
    await delay(200);
    benchmarks = benchmarks.filter(b => b.id !== id);
  },

  // Engine Catalog
  async getEngineCatalog(): Promise<EngineCatalogEntry[]> {
    await delay(200);
    return JSON.parse(JSON.stringify(engineCatalog));
  },

  async toggleEngineCatalogEntry(id: number, enabled: boolean): Promise<EngineCatalogEntry> {
    await delay(200);
    const e = engineCatalog.find(e => e.id === id);
    if (!e) throw new Error("Not found");
    e.enabled = enabled;
    return { ...e };
  },

  async resetEngineCatalog(): Promise<EngineCatalogEntry[]> {
    await delay(300);
    engineCatalog = JSON.parse(JSON.stringify(defaultEngineCatalog));
    return JSON.parse(JSON.stringify(engineCatalog));
  },

  // Routing Rules
  async getRoutingRules(): Promise<RoutingRule[]> {
    await delay(200);
    return JSON.parse(JSON.stringify(routingRules));
  },

  async createRoutingRule(rule: Omit<RoutingRule, "id">): Promise<RoutingRule> {
    await delay(200);
    const r: RoutingRule = { ...rule, id: nextRuleId++ };
    routingRules.push(r);
    return { ...r };
  },

  async updateRoutingRule(id: number, data: Partial<RoutingRule>): Promise<RoutingRule> {
    await delay(200);
    const r = routingRules.find(r => r.id === id);
    if (!r) throw new Error("Not found");
    Object.assign(r, data);
    return { ...r };
  },

  async deleteRoutingRule(id: number): Promise<void> {
    await delay(200);
    routingRules = routingRules.filter(r => r.id !== id);
  },

  async toggleRoutingRule(id: number, enabled: boolean): Promise<RoutingRule> {
    await delay(200);
    const r = routingRules.find(r => r.id === id);
    if (!r) throw new Error("Not found");
    r.enabled = enabled;
    return { ...r };
  },

  async resetRoutingRules(): Promise<RoutingRule[]> {
    await delay(300);
    routingRules = [
      { id: 1, priority: 1, condition_type: "table_type", condition_value: "VIEW", target_engine: "databricks", is_system: true, enabled: true },
      { id: 2, priority: 2, condition_type: "has_governance", condition_value: "row_filter", target_engine: "databricks", is_system: true, enabled: true },
    ];
    return JSON.parse(JSON.stringify(routingRules));
  },

  // Models
  async getModels(): Promise<Model[]> {
    await delay(200);
    return JSON.parse(JSON.stringify(models));
  },

  async trainModel(enabledEngineIds: string[]): Promise<Model> {
    await delay(3000);
    const m: Model = {
      id: nextModelId++, linked_engines: [...enabledEngineIds],
      model_path: `/models/model_${String(nextModelId - 1).padStart(3, "0")}.joblib`,
      accuracy_metrics: { r_squared: 0.82 + Math.random() * 0.1, mae_ms: 30 + Math.floor(Math.random() * 30) },
      is_active: false, created_at: new Date().toISOString(),
      benchmark_count: 5 + Math.floor(Math.random() * 15),
    };
    models.push(m);
    return JSON.parse(JSON.stringify(m));
  },

  async activateModel(id: number): Promise<Model> {
    await delay(200);
    models.forEach(m => m.is_active = m.id === id);
    const m = models.find(m => m.id === id)!;
    return JSON.parse(JSON.stringify(m));
  },

  async deactivateModel(id: number): Promise<Model> {
    await delay(200);
    const m = models.find(m => m.id === id);
    if (!m) throw new Error("Not found");
    m.is_active = false;
    return JSON.parse(JSON.stringify(m));
  },

  async deleteModel(id: number): Promise<void> {
    await delay(200);
    models = models.filter(m => m.id !== id);
  },

  // Query Log
  async getQueryLogs(engineFilter?: string): Promise<LogEntry[]> {
    await delay(200);
    let logs = [...queryLogs];
    if (engineFilter && engineFilter !== "all") {
      logs = logs.filter(l => l.engine.startsWith(engineFilter));
    }
    return logs.slice(0, 20);
  },

  // Utility: count benchmark runs for given engines
  async getBenchmarkCountForEngines(engineIds: string[]): Promise<number> {
    await delay(100);
    // Count unique benchmark results that involve any of the given engine IDs
    let count = 0;
    for (const b of benchmarks) {
      const hasEngine = b.results.some(r => engineIds.includes(r.engine_id));
      if (hasEngine) count += b.results.filter(r => engineIds.includes(r.engine_id)).length;
    }
    return count;
  },
};
