// =============================================================================
// Mock API Layer
// =============================================================================
//
// REAL (wired to backend):
//   - catalog:          Unity Catalog browsing — CatalogBrowser.tsx uses api.get() directly
//   - query:            SQL execution via POST /api/query — CenterPanel.tsx
//   - query logs:       query history via GET /api/logs — CenterPanel.tsx
//   - query detail:     GET /api/query/{id} — CenterPanel.tsx
//   - workspaces:       workspace connect/disconnect — WorkspaceManager.tsx
//   - warehouses:       warehouse list + selection — AppContext + WorkspaceManager
//   - routing rules:    GET/POST/DELETE /api/routing/rules — Phase 8
//   - routing settings: GET/PUT /api/routing/settings — Phase 8
//   - collections:      CRUD + query management via /api/collections — Phase 10
//   - engines:          engine catalog + runtime status via /api/engines — Phase 10
//   - benchmarks:       CRUD + execution via /api/benchmarks — Phase 10
//   - probes:           storage latency probes via /api/latency-probes — Phase 10
//   - models:           ML model listing, activation, training via /api/models — Phase 13
//   - routing profiles: CRUD + default via /api/routing/profiles — Phase 15
//   - model training:   POST /api/models/train with collection_ids — Phase 15
//
// MOCKED (only used when ?mock=true):
//   - executeQuery:     simulated routing + execution with streaming logs
//   - getQueryLogs:     in-memory query history (populated by executeQuery)
//
// Thin API wrappers below delegate to api.* and work in both real and mock mode.
// =============================================================================

import type {
  Collection, CollectionWithQueries, Query,
  QueryExecutionResult, BenchmarkSummary, BenchmarkDetail,
  LogEntry,
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

// ---- Mutable state (mock-only — used by executeQuery/getQueryLogs) ----

const routingSettings = { running_bonus_duckdb: 0.05, running_bonus_databricks: 0.15 };

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

// ---- Mock API ----
export const mockApi = {
  // Collections (thin wrappers — work in both real and mock mode)
  async getCollections(): Promise<Collection[]> {
    return api.get<Collection[]>('/api/collections');
  },

  async getCollection(id: number): Promise<CollectionWithQueries> {
    return api.get<CollectionWithQueries>(`/api/collections/${id}`);
  },

  async createCollection(name: string, description: string): Promise<Collection> {
    return api.post<Collection>('/api/collections', { name, description });
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

  // Query Execution (mock-only — simulates routing pipeline with streaming logs)
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
      execution: { execution_time_ms: execTime },
      columns, rows,
    };
  },

  // Benchmarks (thin wrappers — work in both real and mock mode)
  async getBenchmarks(collectionId?: number): Promise<BenchmarkSummary[]> {
    const params = collectionId != null ? `?collection_id=${collectionId}` : '';
    return api.get<BenchmarkSummary[]>(`/api/benchmarks${params}`);
  },

  async getBenchmark(id: number): Promise<BenchmarkDetail> {
    return api.get<BenchmarkDetail>(`/api/benchmarks/${id}`);
  },

  async createBenchmark(collectionId: number, engineIds: string[]): Promise<BenchmarkSummary> {
    return api.post<BenchmarkSummary>('/api/benchmarks', { collection_id: collectionId, engine_ids: engineIds });
  },

  // Query Log (mock-only — in-memory history populated by executeQuery)
  async getQueryLogs(engineFilter?: string): Promise<LogEntry[]> {
    await delay(200);
    let logs = [...queryLogs];
    if (engineFilter && engineFilter !== "all") {
      logs = logs.filter(l => l.engine.startsWith(engineFilter));
    }
    return logs.slice(0, 20);
  },

  // Storage Latency Probes (thin wrappers — work in both real and mock mode)
  async getStorageLatencyProbes(): Promise<StorageLatencyProbe[]> {
    return api.get<StorageLatencyProbe[]>('/api/latency-probes');
  },

  async runStorageLatencyProbes(): Promise<StorageLatencyProbe[]> {
    const resp = await api.post<{ probes: StorageLatencyProbe[] }>('/api/latency-probes/run', {});
    return resp.probes;
  },
};
