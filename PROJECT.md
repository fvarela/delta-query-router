# Intelligent Query Router for Unity Catalog

## Overview

### What We're Building

An intelligent query routing system that analyzes SQL queries against Unity Catalog tables (Delta, Iceberg, and other registered formats) and automatically routes them to the most cost-effective execution engine while maintaining governance constraints. The system aims to achieve **50%+ cost reduction with less than 20% latency increase** compared to running all queries on Databricks SQL Warehouse.

### The Problem

Organizations using Databricks SQL Warehouse face high costs when executing simple analytical queries that don't require the full power of a distributed compute cluster. Many queries—small aggregations, point lookups, or exploratory analyses on limited datasets—could run faster and cheaper on lightweight single-node engines. However, governance requirements (row-level security, column masking) and the complexity of routing decisions prevent users from manually choosing the right engine for each query.

### The Solution

A smart orchestration layer that:
- Intercepts SQL queries before execution
- Analyzes query complexity, estimated data volume, and governance constraints
- Makes intelligent routing decisions based on cost and latency trade-offs
- Routes simple queries to a containerized DuckDB cluster (cheap, fast)
- Routes complex or governed queries to Databricks SQL Warehouse (powerful, compliant)
- Provides observability through a web UI with real-time metrics and cost tracking

### Core Contribution

The routing algorithm that combines multiple decision factors:
- Query complexity scoring (joins, aggregations, subqueries)
- Table metadata analysis (size, row counts, partitioning)
- Governance constraint detection (row-level security, column masking)
- Warehouse state monitoring (warm/cold, queue length)
- Multi-criteria optimization (weighted cost vs latency scoring)

---

## Design Decisions

### ODQ-1: Collection data model simplification — DECIDED

**Decision (2026-03-14):** Collections are purely a group of queries — no `routing_mode`, no engine info. Routing is determined by the page-level toggle at execution time. Schema uses a separate `queries` table with FK to `collections` (normalized design).

**Schema:**
- `collections`: id, name, description, created_at, updated_at
- `queries`: id, collection_id (FK), query_text, sequence_number

### ODQ-2: Benchmarks as a separate entity — DECIDED (revised 2026-04-05)

**Decision (2026-03-14, revised 2026-04-05):** Benchmarks are a first-class entity with their own DB tables. A benchmark **definition** is the combination of a collection and an engine (1:1 immutable pair). A benchmark **run** is a single execution of a definition, capturing cold-start time and per-query timings. Multiple runs per definition are supported to accumulate training data for ML models.

A warm-up phase precedes each benchmark run: a probe query is sent to each engine to ensure it is warm, and cold-start time is recorded. Engine identity uses a string ID in the `engines` table; temporary engines are provisioned fresh for benchmark runs and torn down afterward.

**Design notes:**
- Engine configurations are portable across workspaces — a SQL Warehouse benchmark result applies to any warehouse with the same config (cluster size, Photon, serverless, region), regardless of workspace. Formalized in ODQ-4.
- DuckDB engines should also support configurable deployment modes (always-on for active engines) and resource settings. Multiple DuckDB configurations can coexist. Formalized in ODQ-4/ODQ-7.
- Cold-start is measured during warm-up, not during benchmark queries. Results contain only warm-engine performance data.
- When users select engines that share a common collection benchmark, they can compare results across engines and train a model from the combined data.

**Schema (revised):**
- `benchmark_definitions`: id, collection_id (FK), engine_id (text, FK to engines), created_at. UNIQUE(collection_id, engine_id)
- `benchmark_runs`: id, definition_id (FK to benchmark_definitions), status, created_at, updated_at
- `benchmark_engine_warmups`: id, benchmark_run_id (FK), engine_id (string), cold_start_time_ms, started_at
- `benchmark_results`: id, benchmark_run_id (FK), engine_id (string), query_id (FK to queries), execution_time_ms, error_message

### ODQ-3: ML models for routing predictions — DECIDED (partially superseded by ODQ-10)

**Decision (2026-03-14):** ML models trained on benchmark data predict execution time per engine. scikit-learn random forest regression. Training runs as a K8s Job, triggered manually via API. Models require explicit user activation after reviewing hold-out validation metrics. If two benchmarks share the same engine set, their training data can be combined.

**Superseded (2026-03-21, revised 2026-03-27):** The single multi-output model design below is superseded by ODQ-10, which uses a **latency-only ML model** paired with **static cost tiers** (per-engine integer 1–10). The framework, training workflow, activation flow, query features, and engine features defined here remain unchanged. The target variables, `models` schema, and routing-time scoring logic are updated in ODQ-10. The `routing_settings` schema is also updated in ODQ-10. Cost prediction via ML or formula was removed — cost is a static engine property (cost tier), not a per-query prediction.

**Model design:**
- **Framework:** scikit-learn (random forest regressor, multi-output)
- **Training:** K8s Job triggered via `POST /api/models/train`. Reads benchmark results from PostgreSQL, trains model, stores serialized model (joblib) and validation metrics
- **Activation:** Manual. User reviews hold-out validation metrics (train/test split) in the UI, then explicitly activates the model via `POST /api/models/{id}/activate`. No model enters the routing path without human review
- **Target variables:** ~~Two regression outputs per engine — `predicted_execution_time_ms` and `predicted_cost_usd`.~~ See ODQ-10 for updated design: latency-only ML model + static cost tiers (no cost prediction).
- **Query features** (extracted via sqlglot AST): `num_tables`, `num_joins`, `num_aggregations`, `num_subqueries`, `has_group_by`, `has_order_by`, `has_limit`, `has_window_functions`, `estimated_data_bytes`, `max_table_size_bytes`, `num_columns_selected`
- **Engine features** (from engine configuration): `engine_type` (databricks_sql/duckdb), `cluster_size`, `has_photon`, `is_serverless`, `memory_gb`
- Features are abstract — no table names, no raw SQL. Models generalize across different datasets and workspaces

**Schema:** See ODQ-10 for updated `models` and `routing_settings` schema.

**Future considerations (not in current scope):**
- New-benchmark notifications: alert the user when benchmark data exists that the active model was not trained on, suggesting retraining
- Automated retraining with configurable triggers

### ODQ-4: Multi-engine support (N warehouses + N DuckDB configs) — DECIDED

**Decision (2026-03-14):** Each engine (Databricks SQL Warehouse or DuckDB configuration) is a row in the `engines` table. DuckDB configurations are separate K8s Deployments, each with its own Service and resource limits — Cluster Autoscaler handles node provisioning when pods can't be scheduled. The `engines` table is built with the first feature that needs it (likely benchmarks), not as a standalone migration. Engine IDs in existing benchmark and model tables become FKs once the engines table lands.

**Engine registry schema:**
- `engines`: id (text PK, e.g. `duckdb:1gb-1cpu`, `databricks:serverless-2xs`), engine_type (text: `databricks_sql` / `duckdb`), display_name, config (JSONB — memory_gb, cpu_cores for DuckDB; cluster_size for Databricks), k8s_service_name (for DuckDB engines — the K8s Service the routing-service calls), cost_tier (integer 1–10), is_active (boolean), created_at, updated_at. **Simplified in Phase 15:** No `catalog_id` FK — the separate `engine_catalog` table concept was abandoned (see ODQ-7 revision). No `is_temporary` or `benchmark_run_id` — temporary engine provisioning deferred. 6 predefined engines (3 DuckDB + 3 Databricks) seeded by schema migration. **Phase 17:** `scale_policy` column removed (was dead metadata).
- `engine_preferences`: id, engine_id (FK to engines), preference_order (int), created_at — stores user-defined engine ordering for fallback routing when no ML model is available

**DuckDB multi-config deployment model:**
- Each DuckDB configuration (e.g., "2GB RAM", "8GB RAM", "16GB RAM") is a separate K8s Deployment + Service
- Resource requests/limits on the Deployment spec control memory and CPU allocation
- The routing-service calls the engine's `k8s_service_name` (e.g., `duckdb-worker-small:8080`, `duckdb-worker-large:8080`)
- On managed K8s (EKS/GKE/AKS), Cluster Autoscaler detects unschedulable pods and provisions new nodes (2-5 min). Spot node pools with `minSize: 0` scale to zero when no large DuckDB pods are needed
- On Minikube (local dev), only the default small config runs; large configs are not deployed

**Databricks multi-warehouse model:**
- Each SQL Warehouse is identified by its configuration (cluster size, Photon, serverless, region), not by workspace-specific ID
- Engine configurations are portable across workspaces: benchmark results for one workspace apply to any warehouse with the same config
- Users select which warehouses are active for routing in the right panel Engines section

**Engine preference ordering:**
- Users set a preference order for fallback routing (when no ML model is available and no hard rules match)
- The preference order is stored in `engine_preferences` and editable in the right panel Engines section (drag-to-reorder or numbered list)

**Implementation ordering:** Option C — the engines table is built with the first feature that needs it, not as a standalone task. Existing `engine_id` string references in `benchmark_engine_warmups`, `benchmark_results`, and `models.linked_engines` will be updated to FKs when the table lands.

### ODQ-5: Routing logic restructure (hard rules → ML → fallback) — DECIDED

**Decision (2026-03-15):** Layered 4-stage routing pipeline replacing the previous deterministic scoring approach:
1. **Mandatory hard rules** (system-defined, `is_system = true`): engine-agnostic access constraints — e.g., "table not externally accessible → smallest enabled Databricks engine." Always applied regardless of routing mode.
2. **User-defined hard rules** (configurable, restorable to defaults)
3. **ML model prediction** (when a model is available for the engine set)
4. **Fallback** to user-defined engine preference order, then DuckDB as ultimate default. No match never rejects a query.

Per-query mode interaction: `smart` runs the full pipeline; `duckdb` and `databricks` apply mandatory rules first, then route to the chosen engine.

**Schema:**
- `routing_rules`: id (serial PK), priority (int), condition_type (text), condition_value (text), target_engine (text), is_system (bool), enabled (bool)
- Mandatory rules seeded by migration, protected from user modification at API level
- Specific mandatory rules deferred to implementation

### ODQ-6: Web UI layout changes — DECIDED

**Decision (2026-03-15):** Unity Catalog browser kept as left panel — navigates catalogs → schemas → tables, shows table metadata on click, quick action loads `SELECT * FROM catalog.schema.table LIMIT 100` into query editor. Batch operations on collections dropped — no "Run All" / "Run Selected" buttons; individual queries run from editor, batch execution done via benchmarks (ODQ-2). Right panel simplified to collection list and query list without checkboxes or selection order tracking. Edited query persistence is deferred/optimistic — edits held in memory with visual "modified" indicator, persisted only on explicit collection save, confirmation prompt on navigation with unsaved changes.

### ODQ-8: UI restructuring — inline workspace and routing management — DECIDED (revised 2026-04-09)

**Decision (2026-03-19, revised 2026-04-09 after Phase 15 Stage A):** Major UI restructuring eliminating the Settings modal in favor of inline management panels. Extensively revised during Phase 15's 34 rounds of UI prototyping. Key changes from original decision preserved; superseded details updated:

1. **Workspaces moved to left panel.** Collapsible header with status dot, expand-on-click for PAT management, connect/disconnect. Catalog browser activates only when connected.

2. **Right panel is routing-only (no tabs).** Stacked sections: Current Settings (read-only live info) → Profile Selector → Routing Settings (mode-dependent engine list) → Routing Priority (3-step segmented button) → conditional Save/Rollback bar. No routing pipeline visualization, no if-then rules UI, no cost/perf slider — all removed during Phase 15.

3. **Three routing modes: `single | smart | benchmark`.** Explicitly selected via segmented button in right panel. Single Engine = radio buttons; Smart Routing = model-driven engine checkboxes; Benchmark = unconstrained multi-select. Replaces the previous 2-state (Single/Multi Engine) design.

4. **Collections & Benchmarks in left panel.** Moved from right panel to left panel as a tab alongside Catalog Browser. Benchmark runs displayed within collection detail view, grouped by engine.

5. **Center panel is query-only (no tabs).** SQL editor + results + query history. The "Engine Setup" tab concept from early Phase 15 was removed in Round 25.

6. **Login flow implemented.** `LoginPage.tsx` with username/password → `POST /api/auth/login` → session token in `sessionStorage`. Auth context wraps entire app.

7. **No Settings modal.** All configuration inline in left panel (workspaces) and right panel (routing).

See ODQ-7 (revised 2026-04-09) for full details on engine management, routing profiles, and benchmark data model. See `.agents/docs/UI-SPEC.md` for complete UI specification.

### ODQ-7: Engine management, benchmark lifecycle & UI redesign — DECIDED (revised 2026-04-09)

**Decision (2026-03-15, revised 2026-04-09 after Phase 15 Stage A — 34 rounds of UI prototyping):** 6 predefined engine configs (3 Databricks Serverless + 3 DuckDB) stored directly in the existing `engines` table — no separate `engine_catalog` table. Engines are global system entities: predefined, seed-only, no user CRUD. The engine catalog concept was introduced (Round 14), removed (Round 15), re-introduced as declarative (Round 16), and permanently removed (Round 23). The `engines` table is the single source of truth for both configuration and runtime.

**Engine management (simplified):**
- All 6 engines shown directly in the right panel's Routing Settings section — no separate catalog view or management dialog.
- **Three routing modes:** `single | smart | benchmark` — explicitly selected via segmented button control.
- **Single Engine mode:** Radio buttons for all engines. User picks one. No ML model involved.
- **Smart Routing mode:** Model dropdown → engine checkboxes (only the model's `linked_engines`). User can uncheck engines to exclude from routing without retraining.
- **Benchmarking mode:** Separate `benchmarkEngineIds` state — unconstrained multi-select across all engines for benchmark runs.
- Databricks engine rows show three-tier disabled state: (1) no workspace connected → grayed out, (2) wrong workspace connected → disabled + warning, (3) correct workspace → interactive, gated by warehouse mapping.

**Engine lifecycle:**
- **DuckDB engines are toggled on/off via `is_active`.** Setting `is_active = true` scales the K8s Deployment to `replicas: 1`; setting `is_active = false` scales to `replicas: 0`. The routing-service has RBAC permissions to patch Deployments. Only `duckdb-1` (small) is active by default; medium and large start with `replicas: 0`. Phase 17 replaced the original `scale_policy` field (which was never used for actual scaling) with direct K8s Deployment scaling on `is_active` toggle.
- **Databricks engines** follow their normal warehouse auto-stop behavior. Warehouses are mapped to engine types per routing profile (see routing profiles below).
- **Temporary engine provisioning** (creating K8s Deployments for benchmark-only DuckDB workers) is deferred — benchmarks run on the permanently deployed engines.

**Routing profiles (NEW — Phase 15):**
Named, persistent routing configurations with full CRUD. Each profile stores the complete routing state:
- `routingMode`: `single | smart | benchmark`
- `singleEngineId`: selected engine in single mode
- `activeModelId`: active ML model (smart mode)
- `enabledEngineIds`: engines participating in smart routing
- `routingPriority`: cost_weight value (0 | 0.5 | 1)
- `workspaceBinding`: auto-derived Databricks workspace reference (implicit — set when user maps a warehouse, cleared via explicit unlink action)
- `warehouseMappings`: `Record<engineId, { warehouse_id, warehouse_name }>` — binds Databricks engine types to actual warehouses in the connected workspace

One profile is the API default (used when accessed programmatically). Users can switch profiles, work with unsaved configurations, save changes, or "Save As" to create new profiles. Benchmark mode is stateless — no profiles involved.

**Schema:**
- `routing_profiles`: id (serial PK), name (text), is_default (boolean), config (JSONB — full RoutingConfig snapshot), created_at (timestamptz), updated_at (timestamptz)

**Benchmark data model (revised):**
- **Benchmark definition** = collection × engine (1:1 pair, immutable). E.g., "TPC-DS 1GB on DuckDB Small" is one benchmark definition.
- **Benchmark run** = a single execution of a benchmark definition. Each run captures cold-start time, per-query timings, and error states.
- Multiple runs per definition are supported — more data improves model training.
- UI shows benchmark runs grouped by engine within each collection. Statistics view (when ≥2 runs) shows per-query averages, min/max, std dev.
- Schema: `benchmark_definitions(id, collection_id, engine_id, created_at)` with UNIQUE(collection_id, engine_id). `benchmark_runs(id, definition_id, status, created_at, updated_at)`. Existing `benchmark_engine_warmups` and `benchmark_results` reference `benchmark_run_id` instead of `benchmark_id`.

**TPC-DS benchmarks:**
- TPC-DS (1GB, 10GB, 100GB) are hardcoded/pre-seeded benchmark collections
- **Hardcoded catalog path:** All TPC-DS data lives in `delta_router_tpcds` catalog with schemas `sf1`, `sf10`, `sf100`. Not user-configurable — deterministic paths enable simple detection without database lookups
- **Cross-workspace visibility:** Unity Catalog catalogs are metastore-scoped with default OPEN isolation — visible from all workspaces sharing the same metastore. GRANTs to `account users` ensure universal access
- **Per-scale-factor detection:** `GET /api/tpcds/detect` returns `{ sf1: bool, sf10: bool, sf100: bool }`. No database tracking needed
- **Idempotent:** Existing scale factors cannot be re-created. Wizard shows "Dataset found" with a green check
- Users can also create custom benchmarks with their own queries

**Routing mode selection (API):**
- `POST /api/query` accepts `routing_mode` (duckdb / databricks / smart) and optionally `engine_id` for direct routing
- Mode determined by the active routing profile: one engine → direct routing; multiple engines → smart routing

**Auth simplification:**
- The web UI has a single access level: admin. No regular user roles. All configuration, benchmarking, and routing management is done by the admin.

**Collection tags:**
- Collections have a `tag` field (`"tpcds"` or `"user"`) to distinguish system TPC-DS collections from user-created ones. TPC-DS collections are read-only in the UI (tagged, lock icon). The tag drives UI display only — no routing behavior difference.

**Model training provenance:**
- Models store `training_collection_ids` (JSONB array of collection IDs) — tracking which collections were used during training. This enables the Model Detail View to show training provenance (which collections, how many runs per engine, effective run counts).

**UI layout (final, Phase 15 Stage A):**
See `.agents/docs/UI-SPEC.md` for the complete specification. Key points:
- **Center panel:** Query-only (no tabs). SQL editor + results + query history.
- **Right panel:** Current Settings (live info panel) → Profile Selector → Routing Settings (mode selector + engine list, mode-dependent) → Routing Priority (3-step segmented button) → Save/Rollback bar. No routing pipeline visualization, no if-then rules UI, no cost/perf slider.
- **Left panel:** Workspaces (collapsible header) → Catalog | Collections & Benchmarks tabs. Benchmark runs live in the collection detail view. TPC-DS setup wizard inline.
- **Mock data mode:** `?mock=true` URL param for frontend development without backend.

**Supersedes:** All previous ODQ-7 revisions (2026-03-15, 2026-04-05). The `engine_catalog` table concept is permanently cancelled.

### ODQ-9: ~~Network latency measurement and portable benchmarks~~ — RETIRED

**Retired (2026-04-11, Phase 17).** Storage latency probes were removed entirely. The ML model trains on raw `execution_time_ms` — no I/O decomposition. The `storage_latency_probes` table, `probes_api.py`, `io_latency_ms` column in `benchmark_results`, and all probe-related code have been deleted. Rationale: storage I/O latency is implicitly learned by the ML model from benchmark execution times at each deployment location — separate probes added complexity without improving routing accuracy.

### ODQ-10: Latency model and cost tiers — DECIDED (revised 2026-03-27)

**Decision (2026-03-21, revised 2026-03-27):** The single multi-output model from ODQ-3 (predicting both `execution_time_ms` and `cost_usd` in one model) is replaced by a **latency model** for ML-based predictions and **static cost tiers** for cost comparison. Real-dollar cost estimation (per-query USD) was investigated and rejected — Databricks bills by warehouse uptime (not per-query), DBU rates vary by region/cloud/warehouse-type, and the resulting numbers would be misleading. Instead, each engine is assigned a relative cost tier (1–10) that enables fair cost comparison without false precision.

**Supersedes:** ODQ-3 target variables, `models` schema, and `routing_settings` schema. All other ODQ-3 elements (framework, training workflow, activation, features) remain unchanged. Also supersedes the original ODQ-10 cost model concept (formula-based `estimated_cost_usd`, `cost_estimation_mode` toggle, ML cost model).

**Latency model:**
- **Target variable:** `execution_time_ms` per engine — the raw benchmark execution time. ~~Previously decomposed into compute_time minus io_latency (ODQ-9), but storage probes were retired in Phase 17.~~
- **At routing time:** Total predicted latency = `predicted_ms` + `cold_start_ms` (from `benchmark_engine_warmups` if engine is cold, 0 if warm). Each component is logged separately in the routing decision for full transparency.
- **Features:** Same query features and engine features as ODQ-3.

**Cost tiers (replaces cost model):**
- Each engine has a `cost_tier` integer (1–10) stored in the `engines` table. 1 = cheapest (e.g., small DuckDB worker), 10 = most expensive (e.g., large Databricks Serverless warehouse).
- Cost tier is a **static property of the engine**, not a per-query prediction. It does not vary by query complexity, runtime, or data size.
- Users set the cost tier when configuring engines. Sensible defaults are suggested based on engine type and size (e.g., DuckDB 4GB → 2, Databricks Medium Serverless → 7).
- **No ML cost model.** Cost tiers are too simple to warrant machine learning — they are a direct lookup from the engine record. The `models` table stores only latency models.
- **No USD estimation.** No `estimated_cost_usd`, no `cost_metrics` table, no DBU rates, no pricing API dependencies.

**Why cost tiers work for routing:**
- The router needs to know *which engine is cheaper*, not *how many dollars a query costs*. Relative ordering is sufficient for the cost vs latency tradeoff.
- A query on a cost_tier=2 DuckDB worker is always cheaper than the same query on a cost_tier=8 Databricks warehouse — the actual dollar amount is irrelevant for routing decisions.
- The scoring formula normalizes cost tiers across enabled engines, so absolute values don't matter — only relative differences.

**Decision logic at routing time:**
1. For each enabled engine, compute: `latency_score = predicted_ms + cold_start`
2. For each enabled engine, look up: `cost_score = engine.cost_tier`
3. Normalize both scores across engines (min-max or z-score)
4. Compute weighted score: `score = fit_weight * normalized_latency + cost_weight * normalized_cost_tier`
5. Select engine with lowest score
6. Weights (`fit_weight`, `cost_weight`) are user-configurable via the "Speed <-> Cost" toggle (exposed in routing settings)

**Note:** ~~Step 5 was previously extended by ODQ-11 (running-engine bonus), but that was removed in Phase 17.~~

**Routing without an ML model (rules-only fallback):**
Smart Routing does **not** require an active ML model. The routing pipeline layers are: System Rules → If-Then Rules → ML predictions → Cost vs Latency Priority weighting. Without a model, the first two layers still function — system rules enforce mandatory constraints (e.g., writes to Databricks) and user-defined if-then rules route queries by pattern matching. Only ML-based latency predictions and priority-weighted scoring are skipped. This means the Cost vs Latency Priority toggle has no effect until a model is selected. The UI communicates this clearly: the ML Models section shows "none active" in its header and guidance text in the expanded state; the Cost vs Latency Priority section shows a hint explaining that weighting applies once a model is selected.

**Updated schema (supersedes ODQ-3 schema and original ODQ-10 schema):**
- `engines`: add `cost_tier` (integer, default 5, CHECK 1–10) — relative cost of running queries on this engine.
- `models`: id, linked_engines (JSONB array of engine_id strings), latency_model (JSONB — r_squared float, mae_ms float, model_path text), training_queries (int), is_active (boolean), created_at, updated_at. Models are **latency-only** — no cost sub-model.
- `routing_settings`: id (singleton, always 1), fit_weight (float, default 0.5), cost_weight (float, default 0.5), updated_at. **Removed:** `cost_estimation_mode` (Phase 9), `running_bonus_duckdb` and `running_bonus_databricks` (Phase 17). **Naming rationale:** "fit" means query-engine architectural fit (not actual execution speed) — simple queries score high for DuckDB, complex queries score high for Databricks.
- **Removed:** `cost_metrics` table (no per-query cost data to store).

**UI implications:**
- **Cost vs Fit Priority toggle:** Positioned as a scoring sub-node in the RoutingPipeline timeline diagram in the right panel Routing tab. Only visible in Smart Routing mode (hidden in Single Engine mode). A discrete 3-step toggle with options: "Low Cost" (fit_weight=0.2), "Balanced" (0.5), "High Fit" (0.8). Maps to `fit_weight` and `cost_weight` (they sum to 1.0). Accessible by clicking the "Priority" sub-node in the Scoring section of the timeline.
- **Pipeline stage info:** Each pipeline stage's configuration is accessible by clicking the corresponding node in the RoutingPipeline timeline diagram. The fixed detail area below the diagram shows the selected stage's content. When nothing is selected, the detail area shows a Pipeline Overview with educational content about how the routing pipeline works.
- **ML Models section:** Models are **latency-only** (not bundles). Model cards show the model name, linked engine count, benchmark count, and a "View Details" link. No type badges on the cards. The "View Details" modal shows training metadata (created date, engines, benchmarks, training queries) and latency model metrics (R², MAE in ms, model path). No cost model metrics.
- **Engines section:** Each engine row includes a cost tier indicator (e.g., "$" to "$$$$" or numeric 1–10) alongside the existing type and specs summary. Cost tier is editable in the engine configuration.
- **Query Detail Modal — routing decision:** Each routing decision shows the latency breakdown: Predicted Time + Cold Start = Total Latency. Scoring breakdown shows latency_score, cost_tier, and weighted_score — making it clear why a particular engine was chosen. No "Estimated Cost" line in USD.

---

### ODQ-11: ~~Running Engine Bonus~~ — RETIRED

**Retired (2026-04-11, Phase 17).** The running engine bonus was removed from both ML and heuristic scoring paths. The `running_bonus_duckdb` and `running_bonus_databricks` columns were dropped from `routing_settings`. Rationale: cold-start time is already captured in `benchmark_engine_warmups` and added at scoring time — a separate flat bonus was redundant and added user-facing complexity. Engine runtime state tracking (`engine_state.py`) remains — it is used for DuckDB health probing and UI status badges, not for scoring adjustments.

**What was retained from the original design:**
- `runtime_state` per engine (ephemeral, in-memory cache) — still tracked by `engine_state.py`
- DuckDB health probes via httpx (Phase 17 replaced hardcoded "running" with actual probes)
- Databricks warehouse state polling via SDK (every 30s)
- UI status dots (green = running, gray = stopped, amber = starting)

### ~~ODQ-12: Storage account authorization for external Delta table access — SUPERSEDED by ODQ-13~~

**Superseded (2026-03-25):** This entire decision is retired. See ODQ-13 for the rationale. Unity Catalog's credential vending mechanism provides DuckDB with short-lived, table-scoped cloud storage tokens — no separate Azure service principal or cloud-level IAM configuration is needed. All ODQ-12 artifacts (UI components, API endpoints, schema, pending fixes) are being removed.

### ODQ-13: Credential vending replaces cloud storage credentials — DECIDED

**Decision (2026-03-25):** DuckDB engines access Delta and Iceberg table data files through Unity Catalog's **credential vending** mechanism, not through a separately configured cloud service principal. This eliminates the need for Azure/AWS IAM configuration, storage account discovery, and connectivity verification that ODQ-12 had introduced.

**Supersedes:** ODQ-12 in its entirety — service principal configuration, storage account discovery, connectivity verification, diagnostic feedback, `storage_account_status` schema, `azure-storage-credentials` K8s Secret, all related API endpoints, and all related UI components.

**How credential vending works:**
- The routing-service (or DuckDB worker) calls `workspace_client.temporary_table_credentials.generate_temporary_table_credentials()` with a table's full name.
- Unity Catalog validates the caller's permissions (table ACLs, `EXTERNAL USE SCHEMA` for managed tables) and returns short-lived, table-scoped cloud storage tokens (AWS STS, Azure SAS, or GCS signed URLs).
- DuckDB uses these tokens to read Delta log and Parquet data files directly from S3/ADLS/GCS.
- Tokens are scoped to the specific table's storage path and expire after a short TTL. No long-lived cloud credentials are needed.

**What this means for the system:**
- The only credential the system needs is the **Databricks workspace connection** (PAT token or OAuth). This is already implemented.
- No `azure-storage-credentials` K8s Secret. No `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` environment variables.
- No storage account discovery, connectivity testing, or diagnostic feedback UI.
- No `storage_account_status` PostgreSQL table.
- No `azure-identity` or `azure-storage-blob` Python dependencies in routing-service.
- Phase 9 (ODQ-12 backend implementation) is cancelled.

**Credential vending requirements and limitations:**
- **External tables:** Credential vending uses the Storage Credential associated with the table's External Location to generate temporary tokens. Works out of the box when Unity Catalog is properly configured.
- **Managed tables:** Require two administrative actions: (1) a metastore admin enables "External data access" on the metastore, and (2) `EXTERNAL USE SCHEMA` privilege is granted on the relevant schema. These are one-time Databricks admin tasks, not Delta Router configuration.
- **Tables with row filters or column masks:** Unity Catalog refuses to vend credentials entirely (binary deny). These tables are already routed to Databricks by system rules.
- **Views, foreign tables, streaming tables, materialized views:** Excluded from credential vending. Already handled by existing system rules.

**Impact on storage latency probes (ODQ-9):**
- DuckDB storage probes still need to read from cloud storage to measure I/O latency. With credential vending, the probe obtains temporary credentials the same way a query would — no separate service principal needed. Probes work for any table that DuckDB can read.

**Impact on routing rules:**
- The ODQ-12 system rule "Table's storage account not accessible → route to Databricks" is no longer needed. If credential vending fails for a table, the `catalog_service.py` returns UNKNOWN metadata, and the routing engine rejects the query with a `RoutingError` — which is the correct behavior per the design decisions made for Task 5.

**UI changes required:**
- Remove `StorageAccountsManager` component from left panel.
- Remove storage account status indicators from catalog browser table detail view.
- Remove storage account color bars from catalog browser tree.
- Remove all storage account state from `AppContext`.
- Remove storage account mock data and mock API functions.

---

### ODQ-14: Benchmark Metrics Architecture — minimal training data — DECIDED

**Decision (2026-03-31):** The benchmark system collects only what the ML model can use at inference time. Most execution metrics (data_scanned_bytes, peak_memory_bytes, credential_vending_ms, parquet_file_count, Databricks total_byte_count) are available only after execution and therefore cannot serve as model features at prediction time. Collecting them adds complexity without improving routing predictions.

**Supersedes:** The earlier "exhaustive metrics collection" concept that proposed capturing per-engine execution internals during benchmarks. Simplifies the benchmark system significantly.

**What the ML model needs:**
- **Input features (available pre-execution):** AST features from `query_analyzer.py` (complexity_score, join_count, agg_count, subquery_count, window_function_count, table_count, statement_type) + table metadata from catalog cache (size_bytes, data_source_format, table_type, has_rls, has_column_masking, external_engine_read_support).
- **Output (prediction target):** `execution_time_ms` per engine.
- **Cost:** NOT predicted by ML. Handled via static engine cost tiers (1–10 scale, per ODQ-10). The router combines predicted latency + cost tier for final decision.

**What benchmarks capture:**
- `(query_text, AST_features, table_metadata, engine_id) → execution_time_ms` — this is the training row.
- **Cold-start captured separately** in `benchmark_engine_warmups` — not mixed into training data. At prediction time, cold-start overhead is added on top of the model's warm-execution prediction.

**What benchmarks skip:**
- `data_scanned_bytes`, `peak_memory_bytes`, `credential_vending_ms` — not available at inference time.
- Databricks Query History API — deferred. Wall-clock time (including network round-trip) is the target metric because that's what the user experiences. Server-reported execution time could theoretically make training targets more accurate but adds API complexity.

**Two-tier metrics strategy:**
- **Exhaustive tier (benchmarks):** Full AST features + table metadata + execution_time_ms + cold-start. Used for ML model training.
- **Light tier (production):** Deferred. Would capture basic observability metrics (latency, engine chosen, routing decision) for monitoring. Not needed until production deployment.

---

### ODQ-15: End-User Authentication & SDK Design — DECIDED

**Decision (2026-04-03):** End users interact with Delta Router through a Python SDK that mirrors the `databricks-sql-connector` interface (DB-API 2.0 / PEP 249). Users authenticate with their existing Databricks PAT + workspace URL — no separate Delta Router credentials needed. The system uses a two-level credential model: a **system identity** (admin-configured PAT, later service principal) for infrastructure operations, and **user identity** (per-session PAT) for access control and Databricks-routed query execution.

**SDK interface:**
The SDK is a pip-installable Python library (`delta-router-sdk`) providing a DB-API 2.0 compatible interface modeled after `databricks-sql-connector`. Users migrate with minimal code changes:

```python
# Before (databricks-sql-connector)
from databricks import sql
conn = sql.connect(server_hostname="workspace.cloud.databricks.com",
                   http_path="/sql/1.0/warehouses/abc123",
                   access_token="dapi...")

# After (delta-router SDK)
from delta_router import sql
conn = sql.connect(server_hostname="delta-router.example.com",
                   access_token="dapi...",
                   databricks_host="workspace.cloud.databricks.com")
```

- `server_hostname` — Delta Router endpoint URL
- `access_token` — user's Databricks PAT (used for authentication, not stored permanently)
- `databricks_host` — Databricks workspace URL (needed for PAT validation and workspace identification)

**DB-API 2.0 methods:** `connect()` → `connection.cursor()` → `cursor.execute(sql)` → `cursor.fetchall()` / `fetchone()` / `fetchmany()` / `description` (column metadata).

**Delta Router extensions (beyond DB-API 2.0):**
- `cursor.execute(sql, engine="duckdb")` — routing override, maps to existing `routing_mode` on `POST /api/query`
- `cursor.routing_decision` — after execution, exposes which engine was chosen, why, and latency breakdown
- `conn.list_engines()` — list available engines and their runtime status

**Authentication flow:**
1. SDK calls `POST /api/auth/token` with `databricks_host` + `access_token` (user's PAT)
2. Routing-service validates the PAT by calling `WorkspaceClient(host, token).current_user.me()`
3. On success: generates a Delta Router session token (opaque hex, server-side TTL of 1 hour), stores user PAT + workspace client in an in-memory session dict keyed by the token. Returns the session token + user identity (username, email) to the SDK
4. On failure: returns 401
5. Subsequent SDK calls use the Delta Router token in `Authorization: Bearer` header
6. On 401 (token expired): SDK automatically re-authenticates using the PAT — transparent to the user, no prompt

**User PAT is not persisted.** It lives only in server memory for the session duration. Pod restart invalidates all sessions — users re-authenticate automatically via the SDK's retry logic.

**Two-level credential model:**

| Operation | Identity used | Rationale |
|---|---|---|
| Validate user identity | User PAT (`current_user.me()`) | Proves user is a valid workspace member |
| Check table access permissions | User PAT (`tables.get()`) | Ensures user can access the tables in their query — Delta Router does not grant broader access than the user already has |
| UC metadata for routing (size, format, governance flags) | System identity | Cached metadata, routing pipeline needs broad read access |
| Credential vending for DuckDB (`EXTERNAL USE SCHEMA`) | System identity | Requires schema-level privilege that only the system identity holds |
| Databricks query execution | User PAT | Preserves user identity on the Databricks audit trail |
| DuckDB query execution | System identity (credential vending) + DuckDB worker | User identity not relevant — DuckDB reads from cloud storage via vended credentials |

**System identity:** Currently the admin-configured PAT stored in K8s Secret (`databricks-credentials`). Designed to be swappable to a Databricks service principal without architectural changes. The system identity needs: workspace-level read access to UC metadata, `EXTERNAL USE SCHEMA` on relevant schemas for credential vending, and `SELECT` on tables for DuckDB execution paths. These are one-time admin configuration tasks.

**Permission check flow:**
1. User submits SQL via SDK
2. Routing-service extracts table names from SQL (sqlglot)
3. Routing-service checks user access: calls `tables.get(table_name)` with the user's PAT for each table
4. If any table returns 403/404 → reject query with clear error ("access denied to table X")
5. If all tables accessible → proceed to routing pipeline using system identity for metadata and execution
6. Edge case: user has access but system identity doesn't → surface error ("Delta Router service identity cannot access table X — contact admin")

**Admin web-ui flow (unchanged):**
- Admin logs in with admin credentials (K8s Secret `admin-credentials`) — existing flow
- Admin configures the system identity (workspace URL + PAT) via the web-ui settings — existing flow
- Admin manages routing rules, engines, and system configuration — existing flow
- The admin login endpoint (`POST /api/auth/login`) remains separate from the SDK auth endpoint (`POST /api/auth/token`)

**REST API note:** The SDK is a thin client over the existing routing-service API (`POST /api/query`, `GET /api/engines`, etc.). Any HTTP client can call these endpoints directly with a Bearer token obtained from `POST /api/auth/token`. The Python SDK adds DB-API 2.0 convenience but is not required.

**Service principal readiness:** The auth design uses the system identity as an abstraction. Migrating from admin PAT to a Databricks service principal requires: (1) configuring SP credentials in the K8s Secret instead of a PAT, (2) initializing `WorkspaceClient` with `client_id` + `client_secret` instead of `token`. No changes to the permission model, session management, or SDK interface.

**Schema changes:** None. The existing `query_logs.user_id` field (currently always "admin") will store the authenticated user's Databricks username. The existing in-memory token store in routing-service is extended to hold per-user sessions (PAT + workspace client) instead of a single admin token.

---

### Execution Engines

**Databricks SQL Warehouse**
- Purpose: Handle complex queries, large-scale aggregations, and all queries requiring governance
- Rationale: Required for row-level security and column masking; already available in the infrastructure; powerful for distributed workloads

**DuckDB (Containerized)**
- Purpose: Execute simple queries on small to medium datasets without governance constraints
- Rationale: Extremely fast for OLAP queries on columnar data; native support for Delta Lake and Iceberg table formats; runs efficiently in single-node containers; 10-50x cheaper than warehouse for eligible queries
- Multiple configurations supported: each DuckDB configuration (e.g., 2GB RAM, 8GB RAM, 16GB RAM) runs as a separate K8s Deployment with its own Service. The routing-service addresses each by its K8s Service name (stored in the `engines` table). Cluster Autoscaler provisions nodes on demand — if a large-memory pod can't be scheduled, the autoscaler adds a node from the configured node pool. In local dev (Minikube), only the small config runs; large configs are skipped
- Supported table formats: Delta Lake (via deltalake-python), Iceberg (via DuckDB's native iceberg extension or pyiceberg). The `data_source_format` field on the Unity Catalog `TableInfo` determines which reader to use.
- External access rules (determines which tables DuckDB can read):
  - EXTERNAL tables with `storage_location` and format DELTA or ICEBERG → DuckDB reads directly from cloud storage using the appropriate format reader
  - MANAGED tables with `HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT` → DuckDB reads via credential vending (read-only, short-lived cloud storage credentials)
  - Tables with row filters or column masks → NOT accessible externally; must route to Databricks SQL Warehouse
  - Views → must be executed on Databricks SQL Warehouse
  - Foreign/federated tables (SQL Server, Snowflake, MySQL, PostgreSQL, etc. registered via Lakehouse Federation) → NOT accessible externally; no `storage_location`, no `HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT`; must always route to Databricks SQL Warehouse which acts as the gateway to the federated source
  - **Credential vending (ODQ-13):** DuckDB accesses table data files through Unity Catalog's credential vending mechanism (`temporary_table_credentials`), which provides short-lived, table-scoped cloud storage tokens. No separate Azure service principal or cloud IAM configuration is required. If credential vending fails for a table, the routing engine rejects the query with a `RoutingError`.
  - **Credential vending implementation:** The duckdb-worker uses a hybrid approach: (1) routing-service passes Databricks host, PAT token, and extracted table names to the worker; (2) `credential_vending.py` calls the UC REST API to get table_id + storage_location, then calls the credential vending API to get a SAS token; (3) `deltalake-python` (Rust core) parses the Delta log — including v2Checkpoint and deletionVectors reader features — and extracts file URIs; (4) ABFSS URIs are converted to signed HTTPS URLs; (5) the SQL is rewritten to replace three-part table names with `read_parquet()` calls pointing at the signed URLs; (6) DuckDB executes the rewritten SQL via its httpfs extension. This approach bypasses both DuckDB's broken `unity_catalog` extension HTTP client and DuckDB's Azure C++ SDK SSL cert issues (caused by TLS interception) by using httpfs (libcurl) for data file access and Python's urllib for API calls.

### Infrastructure

**Terraform**
- Purpose: Provision and manage all infrastructure — Kubernetes cluster, Databricks workspace, Unity Catalog, SQL Warehouse, and supporting Azure resources
- Rationale: Official Terraform Databricks provider covers full setup; ensures reproducible environments; simplifies onboarding

**Kubernetes**
- Purpose: Container orchestration for router, UI, DuckDB workers, and PostgreSQL
- Rationale: Cloud-agnostic (portable across Azure, AWS, GCP, or local); industry-standard deployment; autoscaling support; spot instance integration

**Spot Node Pools**
- Purpose: Run DuckDB workers on low-cost preemptible VMs
- Rationale: 85-90% cost savings vs standard VMs; acceptable eviction risk for stateless query workers; queries fail over to Databricks if workers unavailable

### Data & Metadata

**Unity Catalog (Metadata & Governance)**
- Purpose: Source metadata and governance layer for all table formats registered in the catalog
- Rationale: Part of Databricks environment; provides table metadata (size, schema, partitions, format, storage location); exposes governance rules via API; supports Delta Lake, Iceberg, and foreign/federated tables (via Lakehouse Federation). The `data_source_format` field on `TableInfo` identifies the table format (DELTA, ICEBERG, PARQUET, SQLSERVER, SNOWFLAKE, etc.) and drives format-specific handling in the routing and execution layers

**PostgreSQL**
- Purpose: Store query logs, routing decisions, and table metadata cache
- Rationale: Rich querying for analytics dashboards; ACID guarantees; no vendor lock-in; runs efficiently in Kubernetes as StatefulSet; supports time-series queries for observability

**Correlation ID (Traceability)**
- Every query submission generates a UUID `correlation_id` in the routing-service at the point of entry
- The `correlation_id` is passed through to all backends (DuckDB worker, Databricks) as part of every request
- All log entries across all services reference the same `correlation_id`, making every query's full journey joinable in PostgreSQL
- User identity (`user_id`) is captured once at the routing-service entry point and stored alongside the `correlation_id` in `query_logs`
- Backends (DuckDB worker, Databricks) are stateless with respect to users — they receive and log the `correlation_id` but do not manage sessions or user state

**Metadata Caching Strategy — "warm on browse, lazy on query"**
- Cache table metadata (size, row counts, governance rules) in PostgreSQL with time-to-live to minimize Unity Catalog API calls
- Cache-with-TTL provides fast lookups (5-10ms) for frequently-queried tables while ensuring governance metadata stays fresh
- TTL: uniform 5 minutes for all cached fields (governance and size/format refresh together for simplicity; dual-TTL can be added later if API call volume becomes a concern)
- **Warm on browse**: when a user browses the catalog in the UI (GET /api/databricks/.../tables), the endpoint already receives full TableInfo objects from `tables.list()` — cache metadata for all returned tables at that point, at no extra API cost
- **Lazy on query**: at query time, `get_table_metadata()` checks the cache first; if the user browsed the catalog recently, it's a cache hit; otherwise, fetch on demand from the SDK and cache the result
- No background refresh job — avoids API rate limit concerns and unnecessary fetches for tables nobody queries; if latency from cold-cache SDK calls becomes a measurable issue, parallelizing `get_tables_metadata()` with ThreadPoolExecutor is the first mitigation step
- Provides resilience if Unity Catalog API is temporarily unavailable (stale cache entries can optionally be served past TTL as a future enhancement)

### API & Interface

**FastAPI (Router API)**
- Purpose: REST API for query submission, routing decisions, and metrics retrieval
- Rationale: Modern Python async framework; excellent performance; automatic OpenAPI documentation; easy integration with Databricks and DuckDB SDKs

**React + TypeScript (Web UI)**
- Purpose: Single-page application for system configuration, query submission, Unity Catalog browsing, collection management, and observability
- Rationale: Vite build step produces static assets served by FastAPI; TypeScript provides type safety across the full UI specification; React component model maps cleanly to the multi-panel layout (TopBar, LeftPanel, CenterPanel, RightPanel, SettingsModal); Tailwind CSS + shadcn/ui (Radix primitives) for consistent component styling

### Credential Storage

**Kubernetes Secrets**
- Purpose: Persist Databricks credentials and Azure storage credentials across pod restarts
- Rationale: Kubernetes-native; credentials are base64-encoded and can be encrypted at rest; mounted as environment variables into the routing-service pod (and DuckDB worker pods for storage credentials); avoids storing secrets in PostgreSQL
- Flow: User enters credentials in the web-ui → web-ui calls routing-service API → routing-service writes/updates a K8s Secret via the Kubernetes API → routing-service restarts or reloads to pick up the new environment variables
- RBAC: The routing-service ServiceAccount needs permission to create/update Secrets in its namespace
- Secret name: `databricks-credentials` containing keys: `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (PAT mode) or `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` (service principal mode)

### Authentication

**Admin Login (system configuration)**
- Single admin username and password stored in a K8s Secret (`admin-credentials`)
- Web-UI shows a login form; backend validates against the Secret and returns a session token
- Routing-service API requires a Bearer token in the Authorization header
- No user management, no registration, no roles — just one admin account for system configuration
- Endpoint: `POST /api/auth/login`

**End-User Authentication (SDK / API)**
- End users authenticate with their Databricks PAT + workspace URL via `POST /api/auth/token`
- The routing-service validates the PAT against the Databricks workspace, then issues a Delta Router session token
- User PAT is held in server memory per-session (not persisted) — used for permission checks and Databricks query execution
- System identity (admin PAT or service principal) handles UC metadata, credential vending, and DuckDB execution paths
- See ODQ-15 for full design

### Core Libraries

**sqlglot**
- Purpose: SQL parsing and abstract syntax tree (AST) analysis
- Rationale: Pure Python; mature and well-tested; supports multiple SQL dialects; extracts query structure for complexity scoring

**databricks-sdk**
- Purpose: Unity Catalog integration, SQL Warehouse API access, and all Databricks interactions. The SDK wraps the Databricks REST API and handles authentication, pagination, retries, and token refresh. No direct REST API calls to Databricks are needed.
- Rationale: Official Python SDK; handles authentication and API versioning; provides table metadata and governance information
- Key SDK methods: `w.current_user.me()` (validate connection), `w.warehouses.list()` (SQL Warehouses), `w.catalogs.list()` / `w.schemas.list()` / `w.tables.list()` (Unity Catalog browsing), `w.tables.get(full_name, include_manifest_capabilities=True)` (table details with external access flags), `w.statement_execution.execute()` (run SQL on warehouse), `w.temporary_table_credentials.generate_temporary_table_credentials()` (credential vending for DuckDB)
- `TableInfo` key fields: `table_type` (MANAGED/EXTERNAL/VIEW), `data_source_format` (DELTA/PARQUET/etc.), `storage_location`, `manifest_capabilities` (includes `HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT` and `HAS_DIRECT_EXTERNAL_ENGINE_WRITE_SUPPORT` flags)

**deltalake-python**
- Purpose: Direct Delta Lake table access for DuckDB
- Rationale: Enables DuckDB to read Delta tables without Spark; bindings to Rust Delta library; efficient columnar reads

**DuckDB Iceberg extension / pyiceberg**
- Purpose: Direct Iceberg table access for DuckDB
- Rationale: Enables DuckDB to read Iceberg tables registered in Unity Catalog; DuckDB has a native `iceberg` extension for scanning Iceberg metadata and data files; pyiceberg provides an alternative Python-native path for catalog interaction. The choice between the two will be evaluated during implementation based on credential vending compatibility and read performance

**scikit-learn**
- Purpose: ML model training for routing predictions
- Rationale: Lightweight, no GPU required, well-suited for tabular regression tasks; random forest multi-output regression predicts execution time and cost per engine from benchmark data; models serialized with joblib for storage and loading

### Observability

**PostgreSQL-Based Metrics Store**
- Purpose: Centralized logging of all query executions and routing decisions
- Rationale: Single source of truth for evaluation; enables complex analytical queries for dashboards; supports A/B testing between routing strategies

**Web UI Dashboard**
- Purpose: Real-time visualization of cost savings, latency distributions, and routing accuracy
- Rationale: React SPA with Vite build output served as static files by FastAPI; component-based architecture supports the multi-panel layout

---

## Modules

### routing-service (Core Router)
**Purpose:** Core routing logic that analyzes queries and makes routing decisions  
**Status:** Deployed (Phase 1 scaffolding, Phase 2 backend wiring with PostgreSQL + DuckDB, Phase 3-5 health endpoints)  
**Requirements:**
- Parse SQL queries using sqlglot
- Score query complexity (joins, aggregations, subqueries, table count)
- Extract table names from AST
- Fetch table metadata from Unity Catalog (with caching)
- Check governance constraints (row-level security, column masking)
- Make routing decision based on complexity, data size, and governance
- Execute queries on chosen engine (DuckDB or Databricks)
- Log all decisions and metrics to PostgreSQL

**Tech Stack:** Python, FastAPI, sqlglot, databricks-sdk, deltalake-python, scikit-learn, PostgreSQL client, kubernetes (Python client for K8s API — engine registration, DuckDB deployment management), httpx (DuckDB health probes)

### web-ui (Dashboard)
**Purpose:** Convenience interface for configuring the system, submitting queries, browsing Unity Catalog, managing query collections, and viewing results. The UI is not required — all functionality is exposed via the routing-service API for programmatic use by external services.  
**Status:** Phase 6 backend complete (auth, Databricks credentials, health). React frontend implemented with mock data and extensively redesigned through iterative UX feedback sessions (right panel routing config, left panel workspaces, center panel query editor/results/history). Phase 7 UI redesign complete, including ODQ-9 (storage latency probes UI), ODQ-10 (latency model + cost tiers — discrete Cost vs Latency Priority toggle, decomposed latency in query detail modal), ODQ-11 (Running Engine Bonus). UX Rounds 1-8 complete. **Pipeline redesigned twice:** First replaced separate collapsible sections + info modals with a unified button-accordion layout; then redesigned again into a **compact vertical timeline diagram** with a **fixed detail area** below. The timeline has 4 main nodes (System Rules → If-Then Rules → ML Models → Scoring & Select) with Scoring sub-nodes (Priority, Bonus, Storage) shown as indented items. Default detail area shows a Pipeline Overview with educational content (replacing deleted info modals). All content consolidated into `RoutingPipeline.tsx`. **Layout reorganization (Round 9):** Workspaces collapsed into a compact header with expand-on-click dropdown; Collections/Benchmarks moved from right panel to left panel as a tab alongside Catalog Browser; right panel simplified to routing-only (no tabs); "Add to Collection" button added to center panel action bar. **Phase 8-9:** Query execution, routing rules, catalog browsing, and Databricks credential flows wired to real backend. **Phase 10:** Collections, engines, benchmarks, and storage probes wired to real backend — replaced mock API calls in `src/mocks/api.ts`. **Remaining mocks:** workspaces (multi-workspace management), ML models (training wizard, model activation), routing pipeline stage interactions. **ODQ-13 cleanup pending:** StorageAccountsManager component, storage access indicators in catalog browser, and service principal credential modal (all ODQ-12 mock UI) to be removed — credential vending replaces service principal approach.

**Architecture:** FastAPI backend (server.py) serves Vite-built static assets (index.html + JS/CSS bundles in static/assets/). React source lives in web-ui/frontend/ (development only — not included in production image). The Dockerfile uses a multi-stage build: Node stage runs `npm run build` to produce static assets, Python stage copies the build output and runs FastAPI/uvicorn. Everything is a single-page React app. All API domains (query execution, routing rules, collections, engines, benchmarks, probes, catalog browsing, auth, ML models, routing profiles, benchmark definitions/runs, TPC-DS detection, warehouse-to-engine matching) are wired to real backend endpoints. Remaining mock domain: workspaces (multi-workspace management — currently single-workspace only).

**UI specification:** The complete UI layout, component inventory, data model, cross-panel coordination, and mock mode behavior are documented in `.agents/docs/UI-SPEC.md` (1278 lines). This is the authoritative reference for frontend behavior — updated after each round of UI feedback during Phase 15 Stage A (34 rounds).

**Layout summary (Phase 15 final):** 3-column layout (~20%/50%/30%). Left panel: collapsible WorkspaceManager header + Catalog/Collections tabs (benchmark runs in collection detail view). Center panel: query-only — SQL editor + results + query history with detail modal. Right panel: Current Settings (read-only) → Profile Selector → Routing Settings (3-mode selector + engine list) → Routing Priority → Save/Rollback bar. TopBar: "Delta Router" + username + Sign out. Login page for authentication. Mock data mode via `?mock=true` URL param.

**Tech Stack:** FastAPI (Python), React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui (Radix primitives)

### benchmark-runner (Evaluation)
**Purpose:** Execute query collections as benchmarks across all available engines and measure comparative performance  
**Status:** Implemented within routing-service (`benchmarks_api.py`, Phase 10/15)  
**Note:** Originally planned as a separate service but implemented as API endpoints in routing-service. Full lifecycle: create benchmark definitions (collection × engine), execute runs with warm-up phase, capture per-query execution_time_ms, store results in PostgreSQL. Triggered via `POST /api/benchmarks` from web-ui or API.

### data-populator (TPC-DS Data)
**Purpose:** Populate TPC-DS benchmark tables in the user's Databricks Unity Catalog for testing and benchmarking  
**Status:** Implemented within routing-service (`tpcds_api.py` + `tpcds_queries.py`, Phases 14/16)  
**Note:** Originally planned as a separate service but implemented as API endpoints in routing-service. Full lifecycle: SF detection, preflight checks, SF1 via CTAS from `samples.tpcds_sf1`, SF10/SF100 via Databricks Job running DuckDB `dsdgen`, auto-create `tpcds`-tagged query collections (99 queries per SF), cascade delete. Frontend wizard in `TpcdsWizard.tsx`. All 6 TPC-DS endpoints operational: detect, preflight, create, status poll, list catalogs, delete catalog.

**Tech Stack:** Python, Databricks Jobs API, databricks-sdk

### delta-router-sdk (Python SDK)
**Purpose:** Pip-installable Python client providing DB-API 2.0 compatible interface for end users to submit queries through Delta Router with minimal code changes from `databricks-sql-connector`  
**Status:** Implemented (Phase 12, extended Phase 18). Core query execution: `connect()`, `cursor()`, `execute(profile_id=)`, `fetchall()`/`fetchone()`/`fetchmany()`, `description`, `routing_decision`. Management API: `list_engines()`, `list_profiles()`, `get_profile()`, `get_routing_settings()`. 77 unit tests + 10 integration tests.

**Tech Stack:** Python, httpx

### infrastructure (IaC)
**Purpose:** Provision all new cloud resources and deploy all applications via a single `terraform apply`, connecting to an existing Azure tenant with a pre-existing Unity Catalog metastore  
**Status:** Implemented (Phase 11). Terraform + Helm chart complete. **Known issues:** Helm `files/schema.sql` is stale (frozen at ~Phase 10 level, missing 4 tables from Phases 13-17), Terraform secret names don't match Helm template references (deployment-breaking on AKS). See Pending Fixes. Task 59 deferred pending Azure credentials.

**Scope — What Terraform Creates:**
- Databricks resources inside an existing workspace: dedicated catalog, schemas, SQL Warehouse, service principal, and all necessary permissions
- AKS cluster with spot node pools for DuckDB workers
- Networking and ingress
- Helm releases for all in-cluster applications (routing-service, web-ui, duckdb-worker, postgresql)

**Scope — What Terraform Does NOT Touch:**
- The Databricks workspace itself — pre-existing, referenced by URL
- The Unity Catalog metastore — pre-existing, referenced by ID
- Other workspaces or shared tenant resources

**Prerequisites (must exist before `terraform apply`):**
Documented in `infrastructure/terraform/prerequisites.md`. Key inputs:
- Existing Databricks workspace URL and account ID
- Existing Unity Catalog metastore ID
- Azure subscription and resource group

All external dependencies are declared explicitly as Terraform input variables, making assumptions visible rather than hidden.

**Tech Stack:** Terraform, Helm

**IaC Split:**
- **Terraform** owns all cloud infrastructure and Helm releases via the `helm_release` resource — acting as the bridge between infrastructure and application deployment
- **Helm** owns all in-cluster application resources: Deployments, Services, StatefulSets, ConfigMaps, Secrets, ingress rules. One chart per service
- A single `terraform apply` provisions all infrastructure and deploys all applications end-to-end

**Directory Structure:**
```
infrastructure/
  terraform/
    prerequisites.md  # documents what must exist before terraform apply
    main.tf           # AKS cluster, resource groups, networking
    databricks.tf     # catalog, SQL Warehouse, schemas, service principal, permissions
    helm.tf           # helm_release resources for all charts
    variables.tf      # explicit inputs for all external dependencies
    outputs.tf
  helm/
    routing-service/
    duckdb-worker/
    web-ui/
    postgresql/
```

**Migration Note:** Current raw YAML manifests in `k8s/` will be converted to Helm chart templates when the infrastructure phase begins. This is a straightforward migration — existing YAMLs become parameterized templates with image tags and environment-specific values extracted to `values.yaml`.

---

## API Surface

The routing-service is the single API backend. The web-ui proxies all calls through its own FastAPI layer. All Databricks and Unity Catalog interactions use the `databricks-sdk` Python package (`WorkspaceClient`) — no direct REST API calls to Databricks. Exception: `duckdb-worker/credential_vending.py` uses direct REST API calls (urllib) to the UC table info and temporary-table-credentials endpoints because the duckdb-worker does not have a `databricks-sdk` dependency.

### Routing-Service (`http://routing-service:8000`)

**Health & probes:**
- `GET /health` — K8s liveness/readiness probe
- `GET /health/backends` — connectivity status for PostgreSQL, DuckDB worker, Databricks

**Authentication:**
- `POST /api/auth/login` — admin login (username + password → session token)
- `POST /api/auth/token` — SDK/API user authentication (databricks_host + access_token → Delta Router session token + user identity). See ODQ-15

**Settings:**
- `POST /api/settings/databricks` — save Databricks credentials (PAT or service principal) to K8s Secret
- `GET /api/settings/databricks` — current connection status (never returns credentials)
- `PUT /api/settings/warehouse` — select SQL Warehouse for Databricks-routed queries

**Databricks / Unity Catalog:**
- `GET /api/databricks/warehouses` — list accessible SQL Warehouses
- `GET /api/databricks/catalogs` — list Unity Catalog catalogs
- `GET /api/databricks/catalogs/{catalog}/schemas` — list schemas in a catalog
- `GET /api/databricks/catalogs/{catalog}/schemas/{schema}/tables` — list tables with type and external access flags

**Query execution:**
- `POST /api/query` — submit SQL with optional `profile_id` (uses default profile if omitted). Routing pipeline configured by the profile's config (mode, enabled engines, priority). Also accepts legacy `routing_mode` (duckdb / databricks / smart) for backward compatibility.
- `GET /api/query/{correlation_id}` — retrieve past query result and routing decision

**Collections:**
- `POST /api/collections` — create a collection (name, description, queries)
- `GET /api/collections` — list all collections
- `GET /api/collections/{id}` — get collection with all queries
- `PUT /api/collections/{id}` — update collection metadata
- `DELETE /api/collections/{id}` — delete collection
- `POST /api/collections/{id}/queries` — add query to collection
- `PUT /api/collections/{id}/queries/{query_id}` — update a query
- `DELETE /api/collections/{id}/queries/{query_id}` — remove a query

**Benchmarks (definitions + runs model per ODQ-2 revised):**
- `POST /api/benchmarks` — start a benchmark run (collection_id, engine_ids). Creates benchmark definitions (collection × engine) if they don't exist, then creates a run for each definition
- `GET /api/benchmarks` — list all benchmark definitions (filterable by collection_id, engine_id)
- `GET /api/benchmarks/{id}` — get benchmark definition with all runs
- `GET /api/benchmarks/{id}/runs` — list runs for a benchmark definition
- `GET /api/benchmarks/{id}/runs/{run_id}` — get run details, warmup results, and query results
- `DELETE /api/benchmarks/{id}` — delete a benchmark definition and all its runs
- `DELETE /api/benchmarks/{id}/runs/{run_id}` — delete a specific run

**ML Models:**
- `POST /api/models/train` — trigger model training as K8s Job (from benchmark data for specified engine set)
- `GET /api/models/train/{job_id}` — poll training job status
- `GET /api/models` — list all trained models with validation metrics and activation status
- `GET /api/models/{id}` — get model details (linked engines, metrics, feature importance)
- `POST /api/models/{id}/activate` — activate a model for use in routing
- `POST /api/models/{id}/deactivate` — deactivate a model
- `DELETE /api/models/{id}` — delete a model
- `GET /api/routing/settings` — get routing settings (fit_weight, cost_weight)
- `PUT /api/routing/settings` — update routing settings (fit_weight, cost_weight)

**Routing Rules:**
- `GET /api/routing/rules` — list system rules, ordered by priority
- `PUT /api/routing/rules/{id}/toggle` — enable/disable a system rule

**Engines:**
- `GET /api/engines` — list all 6 predefined engines (active and inactive) with runtime_state
- `GET /api/engines/{id}` — get engine details
- `PUT /api/engines/{id}` — update engine settings (is_active). Cannot change engine_type, config, or other immutable fields. Toggling `is_active` on DuckDB engines auto-scales the K8s Deployment (replicas 0↔1)
- `PUT /api/engines/preferences` — set engine preference order (for fallback routing)
- `GET /api/engines/preferences` — get current engine preference order

**Routing Profiles:**
- `GET /api/routing/profiles` — list all routing profiles
- `POST /api/routing/profiles` — create a new routing profile (name, config JSONB)
- `GET /api/routing/profiles/{id}` — get profile details
- `PUT /api/routing/profiles/{id}` — update profile config
- `DELETE /api/routing/profiles/{id}` — delete a profile (cannot delete default)
- `PUT /api/routing/profiles/{id}/default` — set a profile as the API default

**Log Settings:**
- `GET /api/settings/logs` — get log retention settings (retention_days, max_size_mb)
- `PUT /api/settings/logs` — update log retention settings

**TPC-DS Data:**
- `GET /api/tpcds/detect` — check which scale factors exist (`{ sf1: bool, sf10: bool, sf100: bool }`)
- `GET /api/tpcds/preflight` — check prerequisites (samples available, metastore external access, warehouse configured)
- `POST /api/tpcds/create` — trigger TPC-DS data creation (SF1 via CTAS, SF10/SF100 via Databricks Job)
- `GET /api/tpcds/status/{id}` — poll creation progress
- `GET /api/tpcds/catalogs` — list system-created TPC-DS catalogs
- `DELETE /api/tpcds/catalogs/{name}` — delete a system-created catalog + cascade-delete linked collection

**Query logs:**
- `GET /api/logs` — recent query history (filterable by engine, status)

### Web-UI (`http://web-ui:8501`)

- `GET /api/health` — K8s probe
- `GET /api/health/services` — aggregated health for all 5 services (proxies to routing-service)
- `GET /` — serves static index.html

---

## Future Considerations

Potential integrations and enhancements that would extend the platform's value but are not in scope for the current local-development focus.

### Cloud Deployment Authentication (AKS)

Deploying to managed Kubernetes (AKS) introduces three distinct auth boundaries that the local admin login does not address:

**1. User authentication to web-ui / routing-service API:** Users would authenticate with Azure AD / Entra ID via OAuth2/OIDC. This requires redirect flows, token validation, and session management. The routing-service API would validate Azure AD JWT tokens instead of the simple admin token.

**2. Routing-service authentication to Databricks:** Two approaches: (a) a shared service principal — simpler but loses per-user identity and audit trail, or (b) Azure identity passthrough — the user's Azure AD identity is forwarded to Databricks, preserving per-user permissions. Identity passthrough requires the Databricks workspace to trust the same Azure AD tenant and involves token exchange logic.

**3. Other Azure services calling the routing-service:** Would use Azure Managed Identities for service-to-service auth without credentials.

**Why deferred:** This is substantial infrastructure plumbing (OAuth flows, token exchange, Azure-specific wiring) that doesn't contribute to the core routing algorithm. The API is already structured with `user_id` fields and Bearer token patterns that map cleanly to Azure AD tokens when needed.

### Apache Superset (BI & Dashboarding)
**Value:** Adds a full analyst-facing BI layer on top of delta-router. Data analysts get a proper SQL editor, chart builder, and dashboard composer connected to Delta Lake tables, with query routing handled transparently by delta-router.
**Deployment:** Runs as a pod in the same Kubernetes cluster. Superset connects to delta-router as its database endpoint — analysts never interact with DuckDB or Databricks directly.
**Workflow:** Analysts build and iterate on dashboards locally against the cluster instance. Dashboards can be exported as JSON and imported into a centrally hosted Superset instance for sharing and production use.
**Why it fits:** delta-router becomes the compute layer; Superset becomes the presentation layer. Cost savings from intelligent routing apply automatically to all dashboard queries without any analyst awareness.
**Prerequisite:** Core routing logic (query execution via delta-router) must be working and stable before this integration adds value.

### Multi-Catalog Support (Beyond Unity Catalog)

The current system is built around Databricks Unity Catalog as the metadata and governance layer. However, the routing logic itself is catalog-agnostic — it operates on table metadata (size, format, governance flags, storage location) regardless of where that metadata originates. Future versions could support additional catalog systems:

- **Apache Polaris (Iceberg REST Catalog):** Open-source catalog for Iceberg tables, increasingly adopted as a vendor-neutral alternative
- **AWS Glue Data Catalog:** Common in AWS-native environments, supports both Iceberg and Delta tables
- **Hive Metastore:** Legacy but still widespread; many organizations maintain tables registered here
- **Custom REST catalogs:** Any system that can provide table metadata via API

**Why deferred:** Unity Catalog provides the richest metadata (governance rules, manifest capabilities, credential vending) and is the primary target for the Databricks cost optimization use case. Adding catalog abstraction before the core routing is stable would introduce unnecessary complexity. The system's architecture — catalog metadata cached in PostgreSQL, routing decisions based on abstract table properties — already supports this extension without major refactoring when the time comes.

---

## Ongoing Topics

Open threads from planning sessions. Resolved items are checked off and their conclusions moved to the appropriate section (Design Decisions, Development Phases, etc.).

- [x] **Benchmark metrics architecture (2026-03-31):** Resolved. Two-tier strategy (exhaustive for benchmarks, light for production). Most execution metrics are useless for ML training — only AST features + table metadata + storage probes are available at inference time. See ODQ-14.
- [x] **Phase ordering — benchmarks vs. AKS (2026-03-31):** Resolved. Phase 10 = Benchmark Infrastructure, Phase 11 = Azure AKS Deployment. Benchmarks first because: (a) training data needed before ML model, (b) system is simpler now per ODQ-14, (c) ODQ-9 storage probes make benchmark data portable across deployments.
- [x] **Phase 10 scope definition (2026-04-02):** Resolved. Phase 10 delivered: collections CRUD, engine registry (DB-backed, replacing hardcoded tiers), benchmark execution, storage latency probes, full frontend wiring (replaced mock API calls with real endpoints), type cleanup per ODQ-14. ML model training deferred to a future phase. PRD: `.taskmaster/docs/phase10-benchmark-infrastructure.md`.
- [x] **Phase 11 scope definition (2026-04-02):** Resolved. Azure AKS deployment via Terraform + Helm. Key decisions: (1) Terraform creates Resource Group, AKS, ACR, VNet — cloud-agnostic IaC, not Bicep/az CLI. (2) Single umbrella Helm chart for all 4 services, `values.yaml` + `values-azure.yaml`. (3) Single standard node pool (Standard_B2ms, autoscaler 1-3), no spot instances — thesis demo scale doesn't justify spot complexity; mentioned as production recommendation. (4) NGINX ingress controller with one Azure LB/public IP, two ports: 80→web-ui, 8000→routing-service (both need external access — web-ui is the dashboard, routing-service is the production API for future SDK clients). (5) Secrets via Terraform `kubernetes_secret` from `.tfvars` (gitignored), Key Vault mentioned as production recommendation. (6) PostgreSQL stays StatefulSet with Azure Disk PV. (7) Databricks workspace pre-existing, referenced by host URL. (8) No CI/CD pipeline in GitHub repo (enterprise uses Azure DevOps); deployment triggered manually via Makefile. (9) Existing `k8s/` raw manifests preserved for minikube workflow.
- [x] **End-user authentication & SDK (2026-04-03):** Resolved. Designed (ODQ-15), scheduled as Phase 12. Two-level credential model (system identity + user identity), DB-API 2.0 compatible Python SDK mirroring `databricks-sql-connector`. PRD: `.taskmaster/docs/phase12-end-user-auth-sdk.md`.
- [x] **Phase 13 scope definition (2026-04-04):** Resolved. ML Model Training Pipeline — train latency models from benchmark data (ODQ-3/ODQ-10), integrate into routing pipeline, add engine state polling (ODQ-11). Includes: `models` table, extended feature extraction, training endpoint, model activation, ML inference at routing time, engine state polling, frontend wiring (replace model mocks). PRD: `.taskmaster/docs/phase13-ml-model-training.md`.
- [x] **Phase 14 scope definition (2026-04-04):** TPC-DS Benchmark Data & External Access Management.
- [x] **TPC-DS catalog design (2026-04-09):** Resolved. Hardcoded catalog path `delta_router_tpcds` with schemas `sf1`/`sf10`/`sf100` — not user-configurable. Deterministic paths enable simple detection without database lookups. Cross-workspace visibility confirmed: Unity Catalog catalogs are metastore-scoped with default OPEN isolation, so catalogs created from one workspace are visible from all workspaces sharing the same metastore. After creation, GRANT `USE CATALOG`, `USE SCHEMA`, `SELECT`, `EXTERNAL USE SCHEMA` to `account users` (account-level group, not workspace-local). Create once, use everywhere — no per-workspace setup needed. If a scale factor already exists, wizard shows "found" and blocks re-creation. The `tpcds_catalogs` database table is no longer needed for name tracking (paths are deterministic); may retain for creation job status tracking only.
- [x] **Phase 15 scope definition (2026-04-04, revised 2026-04-06, resolved 2026-04-10):** Stage A (frontend exploration) complete — 34 rounds of UI prototyping on `feature/phase15-ui-redesign`. Key outcomes: engine catalog abandoned, three routing modes, routing profiles, query-only center panel, simplified right panel. Gap analysis completed — 10 backend changes identified. Conclusions documented in ODQ-7 (revised 2026-04-09), ODQ-8 (revised 2026-04-09), and `.agents/docs/UI-SPEC.md`. Stage B (backend) complete — all 14 tasks (97-110) done, 590 tests passing.
- [x] **Phase 17 scope definition (2026-04-10):** Resolved. Four pillars: (1) Engine lifecycle management — drop `scale_policy` column, multi-DuckDB engine on/off via K8s Deployment scaling (replicas 0/1), pre-create Medium/Large Deployments with replicas: 0, extend RBAC to Deployments, update `engine_state.py` to probe DuckDB health instead of hardcoding "running", default only duckdb-1 active. (2) Drop storage latency probes — remove `storage_latency_probes` table, `probes_api.py`, `io_latency_ms` from benchmark_results, probe endpoints, I/O subtraction in model training; ML model trains on raw `execution_time_ms`, scoring formula simplified to `total_latency = predicted_ms + cold_start_ms`. (3) Remove running_bonus — delete from ML scoring path, drop `running_bonus_duckdb`/`running_bonus_databricks` columns from `routing_settings`, keep heuristic fallback as-is (no cold_start added — it's a transitional fallback before first model). (4) Query log cleanup — `log_retention_days` (default 30) and `log_max_size_mb` (default 1024) settings, background purge thread, UI configuration, `GET/PUT /api/settings/logs` endpoints. **Completed 2026-04-11.**
- [ ] **Phase 18 — System Cleanup & Local End-to-End Validation (2026-04-11):** Resolved scope. Four pillars: (1) **Bug fixes**: fix `duckdb-1` k8s_service_name (`duckdb-worker` → `duckdb-worker-small`), sync Helm `files/schema.sql`, fix Terraform secret name mismatch. (2) **Remove user rules**: delete `rules_api.py`, user-defined rule CRUD endpoints, simplify routing pipeline to system rules → ML model → fallback (system rules stay for governance). (3) **SDK alignment**: add `profile_id` on `execute()`, add management methods (`list_profiles()`, `get_profile()`, `list_engines()`, `get_routing_settings()`), update tests. (4) **Deploy & validate**: fresh Minikube deployment, walk through full flow, fix what breaks. No PRD — lightweight execution. Multi-workspace deferred (single-workspace sufficient). Data-populator already implemented in routing-service.
- [ ] **AST analysis data plan for ML training (2026-04-14):** Benchmark results currently store `execution_time_ms` per query. ML training needs AST features (from `query_analyzer.py`) alongside timing data. Where do AST features get stored? Are they computed at training time from the query SQL, or pre-computed at benchmark time? Need to verify the current plan (ODQ-14) covers this end-to-end and identify any gaps.
- [x] **DuckDB warmup accuracy (2026-04-14):** Resolved. Warmup `SELECT 1` was cosmetic — it only tested if the DuckDB process was alive (~10ms), missing the real startup costs (credential vending HTTP connections, SAS token generation, Delta log parsing from Azure). Fixed: warmup now runs `SELECT 1 FROM <first_table> LIMIT 1` through the full credential vending path, so `cold_start_time_ms` accurately captures all one-time costs (~2-6s). Per-query credential vending overhead (200-800ms/table + 2-15s Delta log per table) repeats on every query by design — no caching. This is correct for benchmarks: all queries pay the same overhead, enabling apples-to-apples comparison. Credential caching deferred to production optimization (see Exploratory Ideas).
- [ ] **Benchmark progress feedback (2026-04-13):** Current `POST /api/benchmarks` is synchronous — blocks for the entire run duration with no intermediate progress. Backend fix: make benchmark execution async (background thread, return `run_ids` immediately), add `GET /api/benchmarks/runs/{run_id}/progress` endpoint (returns `{status, total_queries, completed_queries, current_engine, current_query_index, errors}` by counting `benchmark_results` rows). Frontend fix: active benchmark banner in Benchmarks tab with engine name + progress bar (X/N) + elapsed time, poll progress every 2-3s, completion notification + auto-refresh runs list. Benchmark results stay in `benchmark_results` table (not mixed into query_logs). Also discovered during validation: DuckDB health aggregation mismatch (web-ui looked for `duckdb_worker` key but routing-service returns `duckdb-worker-small`), and EUS grant/revoke didn't clear previous error on success — both fixed.

---

## Exploratory Ideas

Speculative concepts worth capturing but with no timeline or commitment. Unlike Future Considerations (concrete integration plans) or Pending Fixes (actionable items), these are open-ended explorations that may or may not materialize.

- [ ] **Remote DuckDB workers deployed near data (2026-03-27)** — **Partially addressed by Phase 11** (AKS deployment co-locates workers with data in the same Azure region). The remaining idea is about workers deployed *outside* the cluster for even more flexibility — e.g., as Azure Container Apps in different regions than the AKS cluster. The current architecture deploys DuckDB workers inside the same K8s cluster as the routing-service and web-ui. Since DuckDB's value is reading directly from cloud storage (ADLS, S3), network latency between worker and storage dominates query time. The idea: allow DuckDB workers to be deployed *outside* the cluster, close to the data — e.g., as an Azure Container App in the same region as the storage account. The routing-service already talks to duckdb-worker over HTTP (`POST /query`), so the transport is location-agnostic. **What this would involve:** (1) A worker registry replacing the single hardcoded endpoint — each worker with a name, URL, region, health status, and tags indicating which storage it's near. (2) A standalone, self-contained DuckDB worker Docker image that can run anywhere (not just K8s), with its own auth and health reporting back to the control plane. (3) Azure deployment tooling (IaC or `az` CLI scripts) to easily spin up a worker in a target region, tagged with a convention (e.g., `delta-router:worker`) for discovery. (4) Cloud authentication — the system would need Azure credentials (service principal or user login) to discover/manage remote resources, and the remote workers need their own auth (mTLS, shared secrets, or managed identity) plus storage credentials. (5) Auto-discovery of tagged resources in an Azure subscription, or as a simpler first step, manual registration ("here's my worker URL and API key"). (6) A second routing decision layer: not just *which engine* but *which worker instance*, factoring in worker location vs. data location. **Key tradeoffs:** Results still travel back to the routing-service over the network, so large result sets could negate the benefit — but for the common case (small results from big data), the win is clear. Trust boundary changes when workers are external. Could start Azure-only or design cloud-agnostic from the start. Container Apps is a better fit than Functions (avoids cold starts and execution time limits). **Implementation effort estimate:** Layers 1–2 (worker registry with URL support + standalone worker image with API key auth) are small and align with ODQ-4 engine registry work — the duckdb-worker is already a self-contained FastAPI service. Layer 3 (Azure deployment tooling — Bicep/Terraform for Container Apps) is a focused IaC chunk. Layer 4 (auto-discovery + cloud auth for scanning subscriptions) is the only genuinely complex part and is fully deferrable — manual registration covers the use case. **When to revisit:** When building the engine registry (ODQ-4), design it with `endpoint_url` support from the start so remote workers slot in naturally later. **Related idea considered and deferred:** Distributed query decomposition across multiple DuckDB workers (each handling a portion of a join where tables live in different storage accounts, then merging partial results). This is essentially building a distributed query engine on top of single-node DuckDB — what Spark/Trino do — and is a massive engineering effort. Not worth pursuing; cross-location joins should route to Databricks instead.

---

- [ ] **Credential vending cache for DuckDB production queries (2026-04-14)** — Currently, every DuckDB query re-fetches UC credentials (2 HTTPS calls per table) and re-parses the Delta log from Azure storage. This is by design for benchmark accuracy (all queries pay the same overhead, enabling apples-to-apples comparison). For production, caching would significantly reduce latency: cache SAS tokens (valid ~1 hour) and resolved parquet URLs (keyed by table name, TTL ~30 min). **Must be toggleable** — off during benchmarking (clean training data), on during production (user experience). Implementation: DuckDB worker env var `CREDENTIAL_CACHE_ENABLED` (default false), in-memory dict with TTL eviction. If enabled during benchmarking, the ML model would need a `cache_enabled` feature, adding complexity to the training pipeline. Start with production-only; benchmark implications addressed later if needed.

## Development Phases

- [x] **Phase 1 - Local Dev Environment:** Minikube cluster, routing-service and web-ui scaffolded, containerized, deployed via K8s manifests
- [x] **Phase 2 - Supporting Infrastructure:** PostgreSQL StatefulSet, DuckDB worker, backend wiring via ConfigMap, correlation_id schema
- [x] **Phase 3 - Service Wiring & System Health:** Health indicators polling every 15s, web-ui ConfigMap
- [x] **Phase 4 - React UI:** Superseded by Phase 5, then revived as Phase 7
- [x] **Phase 5 - Vanilla HTML + jQuery UI:** Single index.html served by FastAPI, no build step, no Node.js. Superseded by Phase 7 React migration.
- [~] **Phase 6 - Databricks Integration (backend only):** Backend complete (tasks 1-6), UI tasks cancelled (tasks 7-13) — jQuery UI work superseded by React migration. Completed: `databricks-sdk` and `kubernetes` dependencies, `admin-credentials` Secret + RBAC manifests, `POST /api/auth/login` with Bearer token middleware, `POST/GET /api/settings/databricks` with K8s Secret persistence, `/health/backends` Databricks status, web-ui proxy routes for auth/settings/warehouses. Not completed (carry forward to Phase 7): `GET /api/databricks/warehouses` and `PUT /api/settings/warehouse` routing-service endpoints, credential reload on startup, all UI components.
- [x] **Phase 7 - React Frontend & Remaining Phase 6 Backend:** React prototype incorporated into web-ui with Vite build pipeline and multi-stage Dockerfile. UI restructured per ODQ-8: workspaces in left panel, routing config in right panel Routing tab, collections in right panel Collections tab. Extensive UI redesign completed based on iterative UX feedback (right panel, left panel, center panel — see web-ui module for details). All frontend features use mock data (`src/mocks/api.ts`). **ODQ-12 mock UI to be removed (per ODQ-13):** StorageAccountsManager component in left panel, storage access indicators in catalog browser, service principal credential modal, and related AppContext state — all superseded by credential vending. Wiring mock API calls to real backend endpoints deferred to Phase 8.
- [x] **Phase 8 - Query Execution, Routing Logic & Catalog Browsing:** Core query execution pipeline: SQL parsing with sqlglot, rule-based routing decisions, execution on DuckDB worker and Databricks SQL Warehouse, Unity Catalog browsing, query logging, and wiring frontend mock API calls to real backend endpoints. After this phase, users can submit SQL and see it routed and executed on real engines. See taskmaster phase8 tag for detailed task breakdown (20 tasks). PRD: `.taskmaster/docs/phase8-query-execution-routing-catalog.md`.
- [x] ~~**Phase 9 - Storage Account Authorization (ODQ-12) — Backend & Real API Wiring:**~~ **Cancelled.** Superseded by ODQ-13 (credential vending). Unity Catalog's credential vending mechanism provides DuckDB with short-lived, table-scoped cloud storage tokens — no separate Azure service principal or storage account authorization is needed.
- [x] **Phase 9 - Databricks Integration Validation:** Connect to a real Databricks workspace and validate all existing integration code end-to-end. Fix bugs discovered in Phase 8 code (health endpoint, K8s Secret persistence), wire remaining mock frontend components (WorkspaceManager, CatalogBrowser gate) to real backend APIs, and validate the full flow: credential save → catalog browse → query execute → routing → logging. **DuckDB credential vending implemented:** duckdb-worker reads Delta tables from Unity Catalog via credential vending (UC REST API → SAS token → deltalake for Delta log parsing → DuckDB read_parquet via httpfs). See taskmaster phase9 tag for detailed task breakdown (13 tasks). PRD: `.taskmaster/docs/phase9-databricks-integration-validation.md`.
- [x] **Phase 10 - Benchmark Infrastructure:** Collections CRUD (7 endpoints), engine registry (DB-backed, 5 endpoints, replacing hardcoded `DUCKDB_TIERS`), benchmark execution (run each query on each enabled engine, capture execution_time_ms per ODQ-14), results storage in PostgreSQL, storage latency probes (ODQ-9, 2 endpoints), type cleanup (removed `data_scanned_bytes` and `cost_model` per ODQ-14). Frontend fully wired — replaced mock API calls in `src/mocks/api.ts` with real backend endpoints for collections, engines, benchmarks, and probes. Auth extracted to `auth.py` module. 8 new PostgreSQL tables, 88 backend tests, 21-step smoke test. PRD: `.taskmaster/docs/phase10-benchmark-infrastructure.md`.
- [x] **Phase 11 - Azure AKS Deployment:** Deploy the full Delta Router stack to Azure using Terraform + Helm. **Motivation:** DuckDB worker latency is ~10x Databricks when running locally — co-locating workers in the same Azure region as the data eliminates network round-trip overhead, which is the core value proposition of the project. **Terraform:** Resource Group, AKS cluster (single Standard_B2ms node pool, autoscaler 1-3), ACR (attached to AKS via managed identity), VNet/subnet. Databricks workspace is pre-existing, referenced by host URL. **Helm:** Single umbrella chart (`infrastructure/helm/delta-router/`) with templates for all 4 services (routing-service, web-ui, duckdb-worker, postgresql). `values.yaml` for defaults, `values-azure.yaml` for AKS-specific config (ACR image paths, resource limits, ingress). **Ingress:** NGINX ingress controller → single Azure Load Balancer → one public IP. Port 80 → web-ui (dashboard), port 8000 → routing-service (production API for external clients/SDK). **Secrets:** Terraform `kubernetes_secret` resources, values from `.tfvars` (gitignored). Azure Key Vault mentioned as production recommendation. **PostgreSQL:** Stays as StatefulSet with Azure Disk PV. **No CI/CD in repo** — enterprise uses Azure DevOps; deployment triggered manually via Makefile targets (`make tf-init`, `make tf-plan`, `make tf-apply`, `make build-push`). Existing `k8s/` raw manifests preserved for minikube workflow. *(Task 59 deferred pending Azure credentials; all infrastructure code complete.)*
- [x] **Phase 12 - End-User Authentication & Python SDK:** Implement ODQ-15. **Backend:** `POST /api/auth/token` endpoint for SDK/API user authentication (Databricks PAT + workspace URL → session token), in-memory session store with TTL, user permission checks (`tables.get()` with user PAT before routing), refactor query execution to use user PAT for Databricks execution and system identity for DuckDB/UC metadata. **SDK:** New `delta-router-sdk/` package with DB-API 2.0 interface (PEP 249) mirroring `databricks-sql-connector` — `connect()`, `cursor()`, `execute()`, `fetchall()`/`fetchone()`/`fetchmany()`, `description`. Routing overrides via `engine` parameter on `execute()`. Routing decision introspection via `cursor.routing_decision`. Transparent token refresh on 401. **Cleanup (folded in):** Remove orphaned frontend files, dead mock functions. **Testing:** SDK unit tests (57 tests, 100% coverage), integration tests (self-skipping), permission check unit tests, dual-identity execution tests. PRD: `.taskmaster/docs/phase12-end-user-auth-sdk.md`.
- [x] **Phase 13 - ML Model Training Pipeline:** Train latency prediction models from benchmark data and integrate them into the routing pipeline (ODQ-3/ODQ-10). **Backend:** `models` table (latency-only per ODQ-10), extended query feature extraction, `POST /api/models/train` (scikit-learn RandomForest, hold-out validation, joblib serialization), model activation/deactivation endpoints, `GET/DELETE /api/models` CRUD. ML inference at routing time: load active model → predict execution time per engine → combine with `cold_start` + cost tier → weighted score → engine selection. Engine state polling: periodic Databricks warehouse state + K8s pod status checks, `runtime_state` caching. **Frontend:** Wire ML Models section (replace mocks) — model list, train button, activate/deactivate, detail view with metrics. **Testing:** Feature extraction tests, training pipeline tests, inference tests, model API endpoint tests. 431 tests passing across routing-service. PRD: `.taskmaster/docs/phase13-ml-model-training.md`.
- [x] **Phase 14 - TPC-DS Benchmark Data & External Access Management:** Two pillars: (1) External access prerequisites for the core product — read-only metastore external access check with warning when disabled, EXTERNAL USE SCHEMA grant/revoke action in catalog browser (strictly scoped to this one permission, no other permissions management). (2) TPC-DS benchmark data wizard — guided UI flow to create managed TPC-DS tables in the user's Unity Catalog. **Hardcoded catalog path:** `delta_router_tpcds` with schemas `sf1`/`sf10`/`sf100` — not user-configurable. Per-SF detection (exists vs needs creation). Cross-workspace access via GRANTs to `account users`. SF1 uses CTAS from `samples.tpcds_sf1` (instant). SF10/SF100 use a Databricks Job running DuckDB's `dsdgen` extension (streaming generation, ~3GB RAM regardless of scale factor, disk-bound). Region awareness: managed tables live in metastore managed storage (workspace region), so co-location is inherent. PRD: `.taskmaster/docs/phase14-tpcds-external-access.md`.
- [x] **Phase 15 - Engine Catalog & UI Redesign:** Three-stage approach. **Stage A (frontend exploration) — COMPLETE:** 34 rounds of iterative UI prototyping with mock data on `feature/phase15-ui-redesign` branch. Key outcomes: engine catalog concept permanently abandoned (Round 23); three routing modes (`single | smart | benchmark`); routing profiles with full CRUD; center panel query-only (no tabs); right panel simplified to Current Settings → Profile Selector → Routing Settings → Routing Priority → Save/Rollback; benchmark data model revised to definitions + runs; collection tags (`tpcds | user`); model training provenance (`training_collection_ids`); ModelsDialog with 3-step creation wizard. Complete UI specification in `.agents/docs/UI-SPEC.md`. **Stage B (backend) — COMPLETE:** 14 Taskmaster tasks (97-110), 590 tests. New tables: `routing_profiles`, `benchmark_definitions`, `benchmark_runs`. Schema changes: `collections` (+tag), `models` (+training_collection_ids). New APIs: routing profiles CRUD, benchmark definitions+runs, TPC-DS detect, warehouse-to-engine matching, profile-aware query execution. PRD: `.taskmaster/docs/phase15-ui-backend-alignment.md`. **Stage C (frontend wiring) — COMPLETE:** 7 Taskmaster tasks (111-117). Wired React UI to Stage B backend APIs: routing profiles CRUD, startup hydration from active_profile_id, benchmark definitions/runs, warehouse engine matching, TPC-DS detection, model training with collection_ids, model activate/deactivate/delete. Cleaned dead mock code (removed 11 unused functions, ~1.6 KB bundle reduction). PRD: `.taskmaster/docs/phase15-stage-c-frontend-wiring.md`.
- [x] **Phase 16 - TPC-DS Query Collections & End-to-End Validation:** Auto-generate TPC-DS query collections (99 standard queries per scale factor) after TPC-DS data creation, with table references rewritten to three-part names. Bridges the gap between data creation (Phase 14) and benchmark/model training (Phase 10/13). Auto-create `tpcds`-tagged read-only collection on data ready, cascade delete on data deletion. Frontend triggers collection reload after wizard success. PRD: `.taskmaster/docs/phase16-tpcds-queries-e2e-validation.md`.
- [x] **Phase 17 - Engine Lifecycle, Scoring Simplification & Log Management:** Four pillars. (1) **Engine lifecycle**: dropped `scale_policy` column, DuckDB on/off via K8s Deployment scaling (replicas 0↔1), Medium/Large Deployments pre-created with `replicas: 0`, `engine_state.py` probes DuckDB health via httpx, default only duckdb-1 active. (2) **Dropped storage probes**: removed `storage_latency_probes` table, `probes_api.py`, `io_latency_ms` from benchmark_results; ML model trains on raw `execution_time_ms`; scoring simplified to `total_latency = predicted_ms + cold_start_ms`. (3) **Removed running_bonus**: dropped from ML and heuristic scoring, removed `running_bonus_duckdb`/`running_bonus_databricks` from `routing_settings`. (4) **Log cleanup**: `log_settings` table (retention_days, max_size_mb), background purge thread (`log_cleaner.py`), `GET/PUT /api/settings/logs`, UI config in right panel. Net -950 lines, 675 tests passing. ODQ-9 and ODQ-11 retired.
- [ ] **Phase 18 - System Cleanup & Local End-to-End Validation:** Four pillars: (1) Bug fixes — `duckdb-1` k8s_service_name, Helm schema.sql sync, Terraform secret names. (2) Remove user rules — delete user-defined rule CRUD, simplify routing pipeline (system rules → ML → fallback). (3) SDK alignment — `profile_id` on execute, management methods (list_profiles, get_profile, list_engines, get_routing_settings). (4) Deploy & validate on Minikube.

---

## Pending Fixes

Small items that don't warrant their own phase but should be addressed. These are folded into the next active phase or handled as quick standalone tasks.

- [x] **PostgreSQL schema: add engines table.** *(Created in Phase 10, Task 35. Simplified vs. original spec: no catalog_id FK, no is_temporary, no benchmark_run_id FK — those are deferred to the engine catalog/managed benchmark lifecycle ODQ-7.)*
- [x] **PostgreSQL schema: drop cost_metrics table.** The `cost_metrics` table stores per-query `estimated_cost_usd` which is no longer computed (cost is now a static engine property via cost tiers). Drop the table and its index. Remove the `cost_metrics` INSERT from `query_logger.py`. *(Folded into Phase 9, Task 22.)*
- [x] **PostgreSQL schema: drop cost_estimation_mode from routing_settings.** The `cost_estimation_mode` column is no longer needed — cost is always a static tier lookup from the engine record. Remove from schema and API. *(Folded into Phase 9, Task 22.)*
- [x] **PostgreSQL schema: add engine_preferences table.** *(Created in Phase 10, Task 35.)*
- [x] **PostgreSQL schema: add routing_rules table.** The `routing_rules` table (id serial PK, priority int, condition_type text, condition_value text, target_engine text, is_system bool, enabled bool) does not yet exist. Mandatory rules seeded by migration with `is_system = true`. Add when implementing the routing pipeline (ODQ-5). *(Folded into Phase 8, Task 1.)*
- [x] ~~**PostgreSQL schema: add engine_catalog table.**~~ Cancelled — engine catalog concept permanently abandoned in Phase 15 (see ODQ-7 revised 2026-04-09). The `engines` table is the single source of truth. 6 predefined engines seeded by migration.
- [x] **PostgreSQL schema: add routing_profiles table.** *(Done in Phase 15 Stage B, Task 97. Full CRUD API in `routing_profiles_api.py`.)*
- [x] **PostgreSQL schema: migrate benchmarks to definitions + runs model.** *(Done in Phase 15 Stage B, Task 98/101. `benchmark_definitions` + `benchmark_runs` tables, refactored `benchmarks_api.py`.)*
- [x] **PostgreSQL schema: add training_collection_ids to models.** *(Done in Phase 15 Stage B, Task 103. JSONB array column on `models` table, `TrainRequest` accepts `collection_ids`.)*
- [x] **PostgreSQL schema: add tag column to collections.** *(Done in Phase 15 Stage B, Task 102. `tag TEXT DEFAULT 'user'`, TPC-DS protection on delete/update.)*
- [x] **Add GET /api/tpcds/detect endpoint.** *(Done in Phase 15 Stage B, Task 104. `tpcds_api.py` checks `delta_router_tpcds.sf{n}` schemas.)*
- [x] **PostgreSQL schema: add scale_policy to engines table.** *(Done in Phase 15 Stage B, Task 109. Later removed in Phase 17 — dead metadata.)*
- [x] **Add PUT /api/engines/{id} endpoint.** *(Done in Phase 15 Stage B, Task 109. Updates `is_active` only. Phase 17 added auto-scaling of K8s Deployments on `is_active` toggle.)*
- [x] **POST /api/query: add optional profile_id parameter.** *(Done in Phase 15 Stage B, Task 110. Profile-aware routing with `_load_profile_config()` and `_profile_config_to_routing_params()`.)*
- [x] **Routing-service RBAC: extend to Deployments.** The routing-service Role already includes `deployments` and `deployments/scale` with `get`, `list`, `patch` permissions. Sufficient for DuckDB engine on/off scaling.
- [x] **PostgreSQL schema: add storage_latency_probes table.** *(Created in Phase 10, Task 35.)*
- [x] **PostgreSQL schema: update models table for latency-only architecture.** *(Done in Phase 13, Task 72. `models` table created with latency-only JSONB, training_queries, linked_engines. No model_type or cost_model fields.)*
- [x] **PostgreSQL schema: add io_latency_ms to benchmark_results.** *(Done in Phase 13, Task 75. Column added as nullable float, populated via `_lookup_io_latency_ms()` at benchmark time.)*
- [x] **PostgreSQL schema: update routing_settings for ODQ-10.** Rename `time_weight` to `latency_weight`, keep `cost_weight`. Remove `cost_estimation_mode` column (cost is now a static engine property via cost tiers, not a per-query estimation). *(Folded into Phase 8, Task 1. `cost_estimation_mode` removal pending — currently in schema but should be dropped.)*
- [x] **Catalog browser: display data_source_format for all tables.** Show the `data_source_format` field (DELTA, ICEBERG, PARQUET, SQLSERVER, SNOWFLAKE, etc.) in the table detail view. Foreign/federated tables should show a distinct red indicator alongside the existing green (DuckDB-readable) and amber (Databricks-only) indicators. *(Done — implemented in Phase 7 ODQ-9/ODQ-10 UI work with three-color bar system: green/amber/red.)*
- [ ] **DuckDB worker: install Iceberg extension and add ICEBERG to routing fallback.** The duckdb-worker currently only installs the httpfs extension (delta extension no longer loaded — parquet files are read via httpfs with signed URLs). DuckDB supports Iceberg via a core extension (`INSTALL iceberg; LOAD iceberg;` — see [DuckDB Iceberg docs](https://duckdb.org/docs/stable/core_extensions/iceberg/overview.html)). Iceberg support would require a parallel reader path in `credential_vending.py`. Until then, Iceberg tables route to Databricks.
- [x] **Routing rules: add foreign/federated table test cases.** *(Done in Phase 16.5 tech-debt cleanup. `test_routing_foreign.py` — 27 tests covering foreign table routing, SQL Server/Snowflake/MySQL rule matching, mixed queries, null storage_location.)*
- [x] **Engines config JSONB: add runtime_state tracking.** *(Done in Phase 13, Task 80. `engine_state.py` module with background polling thread, `runtime_state` cached in memory.)*
- [x] **Routing-service: engine state polling.** *(Done in Phase 13, Task 80. `engine_state.py` polls Databricks warehouses every 30s and DuckDB K8s pods. Cached `runtime_state` used by scoring.)*
- [x] **PostgreSQL schema: update routing_settings for ODQ-11.** Add `running_bonus_duckdb` (float, default 0.05) and `running_bonus_databricks` (float, default 0.15) to `routing_settings`. *(Folded into Phase 8, Task 1.)*
- [x] ~~**PostgreSQL schema: add storage_account_status table.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).
- [x] ~~**K8s Secret: add azure-storage-credentials manifest.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).
- [x] ~~**Routing rules: add storage account inaccessibility system rule.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).
- [x] **Drop `scale_policy` column from engines table.** Dead metadata — not used in routing, engine state tracking, or UI. *(Done in Phase 17, Task 131.)*
- [x] **Drop `storage_latency_probes` table and probes API.** Storage I/O latency is learned by the ML model from benchmark execution times — separate probes are redundant. Removed table, `probes_api.py`, `io_latency_ms` column from `benchmark_results`, and probe-related code in routing/training. *(Done in Phase 17, Tasks 127/130.)*
- [x] **Drop `running_bonus_duckdb` and `running_bonus_databricks` from `routing_settings`.** Cold-start measurement replaces running bonus in ML scoring. Heuristic fallback unchanged. *(Done in Phase 17, Task 129.)*
- [x] **Add `log_retention_days` and `log_max_size_mb` to system settings.** Query logs grow unbounded. Added retention config, background purge thread, and UI. *(Done in Phase 17, Task 134.)*
- [x] **Add DuckDB Medium and Large K8s Deployments.** Pre-created with `replicas: 0` so engine on/off is a scale operation, not create/destroy. *(Already existed in k8s/ directory; confirmed in Phase 17.)*
- [x] **K8s schema.sql: `duckdb-1` k8s_service_name mismatch.** Fixed: `'duckdb-worker'` → `'duckdb-worker-small'` in schema.sql. *(Phase 18.)*
- [x] **Helm chart `files/schema.sql` severely stale.** Fixed: synced from `routing-service/db/schema.sql`. *(Phase 18.)*
- [x] **Terraform secret name mismatch (deployment-breaking on AKS).** Fixed: added `existingSecretName` override to Helm values/templates, Terraform passes literal secret names via `set` blocks. *(Phase 18.)*
- [x] **SDK missing `profile_id` on `execute()`.** Added `profile_id: int | None` kwarg to `Cursor.execute()`. *(Phase 18.)*
- [x] **SDK has no management API methods.** Added `list_engines()`, `list_profiles()`, `get_profile()`, `get_routing_settings()` to `Connection`. 17 new tests. *(Phase 18.)*

---

## Design Principles

**Cloud-Agnostic Architecture**
- Use Kubernetes instead of cloud-specific managed services
- Abstract cloud-specific connectors behind interfaces
- Reproducible on any cloud or local infrastructure

**Modularity**
- Separate concerns: parsing, metadata retrieval, routing decision, execution
- Pluggable routing strategies (enable/disable features via configuration)
- Three routing modes: `single | smart | benchmark` — explicitly selected via segmented button in the right panel. Single Engine routes to one engine; Smart Routing uses the full pipeline with an ML model; Benchmark mode runs collections across multiple engines for training data. The backend routing API accepts `routing_mode` (duckdb / databricks / smart) and optionally `engine_id` for programmatic use.
- Smart Routing uses a layered pipeline (ODQ-5): mandatory hard rules (engine-agnostic access constraints, always applied), user-defined hard rules, ML model prediction, then fallback to engine preference order. Rules stored in `routing_rules` table. Latency/cost weights are user-configurable via routing settings; cost is based on static engine cost tiers (1–10), not per-query USD estimates.

**Observability-First**
- Log every routing decision with full context (inputs, scores, reasoning)
- Track actual vs predicted latencies and cost tier effectiveness
- Enable post-hoc analysis of routing accuracy
- Every query is assigned a `correlation_id` at entry — all logs across all services are joinable by this key

**Cost Optimization**
- Keep one DuckDB worker always warm (eliminate cold starts)
- Use Kubernetes spot nodes for burst capacity (85-90% savings)
- Scale down during idle periods
- DuckDB engine on/off via K8s Deployment replica scaling (0↔1) — controlled through the engines API

---


