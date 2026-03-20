# Intelligent Query Router for Delta Lake

## Overview

### What We're Building

An intelligent query routing system that analyzes SQL queries against Delta Lake tables and automatically routes them to the most cost-effective execution engine while maintaining governance constraints. The system aims to achieve **50%+ cost reduction with less than 20% latency increase** compared to running all queries on Databricks SQL Warehouse.

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

### ODQ-2: Benchmarks as a separate entity — DECIDED

**Decision (2026-03-14):** Benchmarks are a first-class entity with their own DB tables. A benchmark runs all queries in a collection on all available engines, recording results per-engine per-query. A warm-up phase precedes the benchmark: a probe query is sent to each engine to ensure it is warm, and cold-start time is recorded. Engine identity uses a string ID for now; the formal engine registry is deferred to ODQ-4. Benchmarks are triggered from the collection UI on the main page, with a benchmark history list and detail view per collection.

**Design notes:**
- Engine configurations are portable across workspaces — a SQL Warehouse benchmark result applies to any warehouse with the same config (cluster size, Photon, serverless, region), regardless of workspace. To be formalized in ODQ-4.
- DuckDB engines should also support configurable deployment modes (always-on vs on-demand) and resource settings. Multiple DuckDB configurations can coexist. Also deferred to ODQ-4.
- Cold-start is measured during warm-up, not during benchmark queries. Results contain only warm-engine performance data.

**Schema:**
- `benchmarks`: id, collection_id (FK), status, created_at, updated_at
- `benchmark_engine_warmups`: id, benchmark_id (FK), engine_id (string), cold_start_time_ms, started_at
- `benchmark_results`: id, benchmark_id (FK), engine_id (string), query_id (FK to queries), execution_time_ms, data_scanned_bytes, other_metrics (JSONB)

### ODQ-3: ML models for routing predictions — DECIDED

**Decision (2026-03-14):** ML models trained on benchmark data predict execution time and cost per engine. scikit-learn random forest multi-output regression. Training runs as a K8s Job, triggered manually via API. Models require explicit user activation after reviewing hold-out validation metrics. If two benchmarks share the same engine set, their training data can be combined.

**Model design:**
- **Framework:** scikit-learn (random forest regressor, multi-output)
- **Training:** K8s Job triggered via `POST /api/models/train`. Reads benchmark results from PostgreSQL, trains model, stores serialized model (joblib) and validation metrics
- **Activation:** Manual. User reviews hold-out validation metrics (train/test split) in the UI, then explicitly activates the model via `POST /api/models/{id}/activate`. No model enters the routing path without human review
- **Target variables:** Two regression outputs per engine — `predicted_execution_time_ms` and `predicted_cost_usd`. At routing time, the router computes a weighted score per engine: `score = w_time * normalized_time + w_cost * normalized_cost` and picks the lowest. Weights (`w_time`, `w_cost`) are user-configurable via routing settings (exposed as a "Speed ← → Cost" slider in the UI)
- **Query features** (extracted via sqlglot AST): `num_tables`, `num_joins`, `num_aggregations`, `num_subqueries`, `has_group_by`, `has_order_by`, `has_limit`, `has_window_functions`, `estimated_data_bytes`, `max_table_size_bytes`, `num_columns_selected`
- **Engine features** (from engine configuration): `engine_type` (databricks_sql/duckdb), `cluster_size`, `has_photon`, `is_serverless`, `memory_gb`
- Features are abstract — no table names, no raw SQL. Models generalize across different datasets and workspaces

**Schema:**
- `models`: id, linked_engines (JSONB array of engine_id strings), model_path (file path to serialized model), accuracy_metrics (JSONB), is_active (boolean), created_at, updated_at
- `routing_settings`: id (singleton, always 1), time_weight (float, default 0.5), cost_weight (float, default 0.5), updated_at

**Future considerations (not in current scope):**
- Region-awareness: warn the user if DuckDB engine and data are in different regions, which would invalidate benchmark results from same-region runs
- New-benchmark notifications: alert the user when benchmark data exists that the active model was not trained on, suggesting retraining
- Automated retraining with configurable triggers

### ODQ-4: Multi-engine support (N warehouses + N DuckDB configs) — DECIDED

**Decision (2026-03-14):** Each engine (Databricks SQL Warehouse or DuckDB configuration) is a row in the `engines` table. DuckDB configurations are separate K8s Deployments, each with its own Service and resource limits — Cluster Autoscaler handles node provisioning when pods can't be scheduled. The `engines` table is built with the first feature that needs it (likely benchmarks), not as a standalone migration. Engine IDs in existing benchmark and model tables become FKs once the engines table lands.

**Engine registry schema:**
- `engines`: id (string PK, e.g. `databricks:small-serverless`, `duckdb:8gb-ram`), engine_type (enum: `databricks_sql` / `duckdb`), display_name, config (JSONB — cluster_size, has_photon, is_serverless, memory_gb, region, etc.), k8s_service_name (for DuckDB engines — the K8s Service the routing-service calls), catalog_id (FK to engine_catalog, nullable — NULL for manually registered engines), is_temporary (bool, default false — true for benchmark-created engines), benchmark_id (FK to benchmarks, nullable — which benchmark created this temporary engine), is_active (boolean), created_at, updated_at
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

### ODQ-8: UI restructuring — inline workspace and routing management — DECIDED

**Decision (2026-03-19):** Major UI restructuring eliminating the Settings modal in favor of inline management panels. Key changes:

1. **Workspaces moved to left panel.** Multiple Databricks workspaces can be added and managed (name, URL, PAT token) directly in the left panel above the Unity Catalog browser. Each workspace has connect/disconnect/delete actions. The catalog browser activates only when a workspace is connected.

2. **Right panel split into two tabs: Routing and Collections.** The Routing tab contains all routing configuration inline (no modal): Engines, Run Mode, Rules, and ML Model sections stacked vertically. The Collections tab retains the collection list, query list, and benchmark functionality.

3. **Run mode simplified to 2-state: Single Engine / Multi Engine.** Replaces the previous 3-state toggle (DuckDB / Databricks / Smart Router) that was planned for the center panel. In Single Engine mode, user selects one engine via radio buttons. In Multi Engine mode, user selects multiple engines via checkboxes, and the Rules + ML Model sections become visible for routing configuration.

4. **Engines section shows contextual Databricks warning.** When no workspace is connected, only DuckDB engines are listed and a red message reads "Select a Databricks Workspace to enable Databricks Engines."

5. **Rules section simplified.** Titled "Rules" (not "Hard Rules"). Shows only custom (non-system) rules in a 4-column table: Condition (table name / data size / table complexity), Comparator (greater than / less than / equal to), Value, Target Engine (DuckDB / Databricks). Add/delete via inline form. Only visible in Multi Engine mode.

6. **ML Model section inline.** Shows trained models with radio-button activation, compatibility check against enabled engines, expandable details, and "Train New Model" button. Only visible in Multi Engine mode.

7. **No Settings modal.** All configuration previously planned for a modal (Databricks connection, engine selection, warehouse selection) is now handled inline in the left panel (workspaces) and right panel (engines/routing).

8. **No login flow / auth context in current frontend.** Authentication is deferred — the frontend currently operates without a login screen or Bearer token injection. Auth will be added when the frontend is wired to the real backend.

### ODQ-7: Engine catalog & managed benchmark lifecycle — DECIDED

**Decision (2026-03-15):** Predefined catalog of 6 engine configs: 3 Databricks Serverless (2X-Small, Medium, Large) and 3 DuckDB (2GB/2CPU, 8GB/4CPU, 16GB/8CPU). Catalog stored in `engine_catalog` PostgreSQL table, distinct from live `engines` table — describes what can be instantiated, not what currently exists. Predefined configs seeded by migration with `is_default = true`; users can add custom configs, defaults can be disabled but not deleted.

**Benchmark lifecycle:** User selects configs from catalog → confirmation dialog with cost warning → temporary engines created in parallel → wait for ready (timeout 10min Databricks, 2min DuckDB) → warm-up probe → benchmark queries → cleanup all temporary engines. Partial failure: continue with remaining engines, report failures. Cold-start time stored in `benchmark_engine_warmups` (per-benchmark observation). Orphan protection via benchmark ID tags and TTL-based cleanup job.

**Schema:**
- `engine_catalog`: id (serial PK), engine_type (enum), display_name, config (JSONB), is_default (bool), enabled (bool), created_at, updated_at

---

## Architecture

### Execution Engines

**Databricks SQL Warehouse**
- Purpose: Handle complex queries, large-scale aggregations, and all queries requiring governance
- Rationale: Required for row-level security and column masking; already available in the infrastructure; powerful for distributed workloads

**DuckDB (Containerized)**
- Purpose: Execute simple queries on small to medium datasets without governance constraints
- Rationale: Extremely fast for OLAP queries on columnar data; native Delta Lake support; runs efficiently in single-node containers; 10-50x cheaper than warehouse for eligible queries
- Multiple configurations supported: each DuckDB configuration (e.g., 2GB RAM, 8GB RAM, 16GB RAM) runs as a separate K8s Deployment with its own Service. The routing-service addresses each by its K8s Service name (stored in the `engines` table). Cluster Autoscaler provisions nodes on demand — if a large-memory pod can't be scheduled, the autoscaler adds a node from the configured node pool. In local dev (Minikube), only the small config runs; large configs are skipped
- External access rules (determines which tables DuckDB can read):
  - EXTERNAL tables with `storage_location` → DuckDB reads directly from cloud storage
  - MANAGED tables with `HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT` → DuckDB reads via credential vending (read-only, short-lived cloud storage credentials)
  - Tables with row filters or column masks → NOT accessible externally; must route to Databricks SQL Warehouse
  - Views → must be executed on Databricks SQL Warehouse

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

**Delta Lake with Unity Catalog**
- Purpose: Source data storage and metadata/governance layer
- Rationale: Part of Databricks environment; provides table metadata (size, schema, partitions); exposes governance rules via API; industry-standard lakehouse format

**PostgreSQL**
- Purpose: Store query logs, routing decisions, cost metrics, and table metadata cache
- Rationale: Rich querying for analytics dashboards; ACID guarantees; no vendor lock-in; runs efficiently in Kubernetes as StatefulSet; supports time-series queries for observability

**Correlation ID (Traceability)**
- Every query submission generates a UUID `correlation_id` in the routing-service at the point of entry
- The `correlation_id` is passed through to all backends (DuckDB worker, Databricks) as part of every request
- All log entries across all services reference the same `correlation_id`, making every query's full journey joinable in PostgreSQL
- User identity (`user_id`) is captured once at the routing-service entry point and stored alongside the `correlation_id` in `query_logs`
- Backends (DuckDB worker, Databricks) are stateless with respect to users — they receive and log the `correlation_id` but do not manage sessions or user state

**Metadata Caching Strategy**
- Cache table metadata (size, row counts, governance rules) with time-to-live to minimize Unity Catalog API calls
- Cache-with-TTL provides fast lookups (5-10ms) for frequently-queried tables while ensuring governance metadata stays fresh
- TTL: 5 minutes for security-critical fields, 30 minutes for size statistics
- Cache misses automatically fetch from Unity Catalog and update the cache
- Provides resilience if Unity Catalog API is temporarily unavailable

### API & Interface

**FastAPI (Router API)**
- Purpose: REST API for query submission, routing decisions, and metrics retrieval
- Rationale: Modern Python async framework; excellent performance; automatic OpenAPI documentation; easy integration with Databricks and DuckDB SDKs

**React + TypeScript (Web UI)**
- Purpose: Single-page application for system configuration, query submission, Unity Catalog browsing, collection management, and observability
- Rationale: Vite build step produces static assets served by FastAPI; TypeScript provides type safety across the full UI specification; React component model maps cleanly to the multi-panel layout (TopBar, LeftPanel, CenterPanel, RightPanel, SettingsModal); Tailwind CSS + shadcn/ui (Radix primitives) for consistent component styling

### Credential Storage

**Kubernetes Secrets**
- Purpose: Persist Databricks credentials (PAT or service principal details) across pod restarts
- Rationale: Kubernetes-native; credentials are base64-encoded and can be encrypted at rest; mounted as environment variables into the routing-service pod; avoids storing secrets in PostgreSQL
- Flow: User enters credentials in the web-ui Settings section → web-ui calls routing-service API → routing-service writes/updates a K8s Secret via the Kubernetes API → routing-service restarts or reloads to pick up the new environment variables
- RBAC: The routing-service ServiceAccount needs permission to create/update Secrets in its namespace
- Secret name: `databricks-credentials` containing keys: `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (PAT mode) or `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` (service principal mode)

### Authentication

**Admin Login (local development scope)**
- Single admin username and password stored in a K8s Secret (`admin-credentials`)
- Web-UI shows a login form; backend validates against the Secret and returns a session token
- Routing-service API requires a Bearer token in the Authorization header (same token)
- No user management, no registration, no roles — just one admin account
- The `user_id` field on queries is always "admin" for now; the field exists for forward compatibility

This is sufficient for local development on Minikube where access is via port-forward. It demonstrates that the system is access-controlled without introducing cloud identity dependencies.

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

**scikit-learn**
- Purpose: ML model training for routing predictions
- Rationale: Lightweight, no GPU required, well-suited for tabular regression tasks; random forest multi-output regression predicts execution time and cost per engine from benchmark data; models serialized with joblib for storage and loading

### Observability

**PostgreSQL-Based Metrics Store**
- Purpose: Centralized logging of all query executions, routing decisions, and cost calculations
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

**Tech Stack:** Python, FastAPI, sqlglot, databricks-sdk, deltalake-python, scikit-learn, PostgreSQL client, kubernetes (Python client for K8s API — engine registration, DuckDB deployment management)

### web-ui (Dashboard)
**Purpose:** Convenience interface for configuring the system, submitting queries, browsing Unity Catalog, managing query collections, and viewing results. The UI is not required — all functionality is exposed via the routing-service API for programmatic use by external services.  
**Status:** Phase 6 backend complete (auth, Databricks credentials, health). React frontend implemented with mock data and extensively redesigned through iterative UX feedback sessions (right panel routing config, left panel workspaces, center panel query editor/results/history). Phase 7 UI redesign complete; wiring to real backend not yet started.

**Architecture:** FastAPI backend (server.py) serves Vite-built static assets (index.html + JS/CSS bundles in static/assets/). React source lives in web-ui/frontend/ (development only — not included in production image). The Dockerfile uses a multi-stage build: Node stage runs `npm run build` to produce static assets, Python stage copies the build output and runs FastAPI/uvicorn. Everything is a single-page React app. The frontend currently runs entirely on mock data (src/mocks/api.ts) — no real HTTP calls to the backend yet.

**Single-Page Layout:**

**Top bar:** "Delta Router" header. Health indicators and Settings modal are not yet implemented — deferred per ODQ-8.

**Left panel — Workspaces + Unity Catalog Browser (20% width):**
- **Workspaces section (top):** Compact workspace rows — each shows name, URL, and status. PAT token management via a Key icon button that opens a modal with password input (show/hide toggle), Save/Cancel. Connect/disconnect and delete actions per workspace. Status shows "No token", "Token set — ready to connect", or "Connected". Add new workspaces via inline form (name + URL).
- **Catalog Browser (below workspaces):** Headed with "Catalog Browser" title and blue Database icon. Tree navigation: catalogs → schemas → tables. Clicking a table shows its details (type, format, size, external access flags, columns). "Load Sample Query" button populates editor with `SELECT * FROM catalog.schema.table LIMIT 100`. Color indicator shows which tables DuckDB can read (green) vs not (amber). Only active when a workspace is connected — otherwise shows "Connect to a workspace to browse catalogs."

**Center panel — Query Editor + Results + Query History (50% width):**
- **Query Editor (fixed top):** SQL textarea for writing and editing queries. "Run" button to execute the current query (disabled when no query entered).
- **Results area (fixed, non-scrollable):** Shows execution metrics (engine, latency, cost, rows) and a data table limited to 10 rows maximum. No routing decision details here — those live in the query detail modal.
- **Query History (scrollable, takes remaining space):** The only scrollable area in the center panel. Sticky table header. Rows show timestamp, query preview, engine, status badge, latency, and cost. Completed rows are clickable (`cursor-pointer` + hover highlight); running rows are not clickable. No "Details" button column.
- **Query Detail Modal:** Opens when clicking a completed history row. Contains: header with full query text + close button (X), summary row (timestamp, engine, status badge, latency, cost), Routing Decision in a grid layout (Engine, Stage, Reason, Complexity), and a Routing Log in dark terminal-style display showing color-coded streaming events by level (info/rule/decision/warn/error) and stage ([PARSE]/[RULES]/[ML]/[ENGINE]/[EXEC]/[DONE]). Closes on backdrop click, close button, or Escape key.

**Right panel — Routing + Collections (30% width):**
Two tabs: **Routing** and **Queries & Benchmarks** (renamed from "Collections").

*Routing tab:*
- **Passive routing mode indicator:** Shows "Direct" (single engine) or "Smart Routing" (multiple engines) based on how many engines are enabled — no toggle button.
- **Workflow visualization:** Pipeline graphic showing Query → Rules → ML Model → Engine, illustrating the routing stages.
- **Rules section:** Titled "Rules" with a count header showing active rules. Simplified inline display with a modal for full rule management (add/edit/delete, move up/down priority). Only visible when Smart Routing is active.
- **ML Models section:** Count header showing compatible models. Radio-button activation with compatibility check against enabled engines. "Train New Model..." subtle link opens a 3-step train wizard panel (select collection → configure → review & train). Only visible when Smart Routing is active.
- **Engines section:** Table layout with columns: checkbox | Type icon | Engine name | Specs summary. Always checkboxes (no radio buttons). Databricks engines show a subtle indicator and are hidden when no workspace is connected. Single engine triggers "Direct" mode; multiple engines trigger "Smart Routing" mode. Empty state message when only one engine is enabled.

*Queries & Benchmarks tab (renamed from Collections):*
- "Query Collections" header with explanatory text
- Collection items with query counts
- Clicking opens collection detail with ordered query list
- Benchmark functionality per collection

**Collection data model:** See ODQ-1 for schema. Collections are purely groups of queries — no routing mode stored. All saved queries belong to a collection.

**Benchmarks** (accessible when a collection is open in the Collections tab):
- "Run Benchmark" button with progress stages (Provisioning engines → Warming up → Running queries → Cleaning up → Complete)
- Benchmark history list showing past runs per collection
- Clicking a benchmark shows details: warm-up times per engine, results matrix (queries × engines) with color highlighting for best/worst times

**State management:** Global AppContext provides: editor state (SQL, results, collection context), workspaces (list + connected workspace), engines (catalog entries, enabled IDs), routing mode (derived from engine count — Direct vs Smart Routing), models (list + active model ID), query history (with per-query routing events and decisions), panel mode (run/train for the right panel train wizard). All data loaded from mock API on mount.

**Tech Stack:** FastAPI (Python), React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui (Radix primitives)

### benchmark-runner (Evaluation)
**Purpose:** Execute query collections as benchmarks across all available engines and measure comparative performance  
**Status:** Not started  
**Requirements:**
- A benchmark runs all queries in a collection on all specified engines (SQL Warehouses + DuckDB instances)
- Before running queries, a warm-up phase sends a probe query (`SELECT 1`) to each engine and records cold-start time in `benchmark_engine_warmups`
- Once all engines are confirmed warm, benchmark queries execute and results are recorded per-engine per-query in `benchmark_results`
- TPC-DS is a pre-built collection with 99 queries, loaded during data-populator setup
- Measure and log execution time, data scanned, and other metrics for every query on every engine
- Engine identity uses the `engines` table: each engine has a unique string ID (e.g., `databricks:small-serverless`, `duckdb:8gb-ram`) with configuration metadata (ODQ-4)
- Triggered from the web-ui collection panel (main page) or via API (`POST /api/benchmarks`)
- Benchmark history is viewable per-collection: list of past runs with click-to-view details and delete capability
- Depends on data-populator having completed successfully for TPC-DS collection

**Tech Stack:** Python, databricks-sdk

### data-populator (Test Data)
**Purpose:** Populate Delta Lake tables from the TPC-DS benchmark dataset for testing and benchmarking  
**Status:** Not started  
**Requirements:**
- Generate TPC-DS data using DuckDB's native `tpcds` extension (no external download needed)
- Support configurable scale factors: SF=1 for local dev, SF=100 for cloud/benchmarking
- Write all 24 TPC-DS tables as Delta Lake format using deltalake-python
- Target storage is configurable: local path (dev) or S3/ADLS (cloud)
- Upload Delta tables to Databricks Unity Catalog and register as external tables
- Apply sample governance rules (row-level security, column masking) to a subset of tables for governance routing tests
- Runs as a Kubernetes Job, triggerable via the routing-service API (`POST /api/ingest/tpcds`)
- Job status is queryable so the web-ui can poll and display progress

**TPC-DS Table Set (24 tables):** call_center, catalog_page, catalog_returns, catalog_sales, customer, customer_address, customer_demographics, date_dim, household_demographics, income_band, item, promotion, reason, ship_mode, store, store_returns, store_sales, time_dim, warehouse, web_page, web_returns, web_sales, web_site, dbgen_version

**Tech Stack:** Python, DuckDB (tpcds extension), deltalake-python, databricks-sdk

### infrastructure (IaC)
**Purpose:** Provision all new cloud resources and deploy all applications via a single `terraform apply`, connecting to an existing Azure tenant with a pre-existing Unity Catalog metastore  
**Status:** Not started  

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

The routing-service is the single API backend. The web-ui proxies all calls through its own FastAPI layer. All Databricks and Unity Catalog interactions use the `databricks-sdk` Python package (`WorkspaceClient`) — no direct REST API calls to Databricks.

### Routing-Service (`http://routing-service:8000`)

**Health & probes:**
- `GET /health` — K8s liveness/readiness probe
- `GET /health/backends` — connectivity status for PostgreSQL, DuckDB worker, Databricks

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
- `POST /api/query` — submit SQL with `routing_mode` (duckdb / databricks / smart). Routing pipeline is configured server-side (rules, ML model, preferences) — no per-query parameters.
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

**Benchmarks:**
- `POST /api/benchmarks` — create and start a benchmark (collection_id, catalog_engine_ids). Temporary engines are created from selected catalog entries, benchmarked, then cleaned up.
- `GET /api/benchmarks` — list all benchmarks (filterable by collection_id)
- `GET /api/benchmarks/{id}` — get benchmark details, warmup results, and query results
- `DELETE /api/benchmarks/{id}` — delete a benchmark and its results
- `DELETE /api/benchmarks?collection_id={id}` — delete all benchmarks for a collection

**ML Models:**
- `POST /api/models/train` — trigger model training as K8s Job (from benchmark data for specified engine set)
- `GET /api/models/train/{job_id}` — poll training job status
- `GET /api/models` — list all trained models with validation metrics and activation status
- `GET /api/models/{id}` — get model details (linked engines, metrics, feature importance)
- `POST /api/models/{id}/activate` — activate a model for use in routing
- `POST /api/models/{id}/deactivate` — deactivate a model
- `DELETE /api/models/{id}` — delete a model
- `GET /api/routing/settings` — get routing settings (including time/cost weight slider)
- `PUT /api/routing/settings` — update routing settings (time/cost weights, etc.)

**Routing Rules:**
- `GET /api/routing/rules` — list all rules (system + user-defined), ordered by priority
- `POST /api/routing/rules` — create a user-defined rule
- `GET /api/routing/rules/{id}` — get a single rule
- `PUT /api/routing/rules/{id}` — update a user-defined rule (403 if is_system)
- `DELETE /api/routing/rules/{id}` — delete a user-defined rule (403 if is_system)
- `PUT /api/routing/rules/{id}/toggle` — enable/disable any rule (including system rules)
- `POST /api/routing/rules/reset` — delete all user-defined rules, re-seed system defaults

**Engines:**
- `GET /api/engines` — list all registered engines (active and inactive)
- `POST /api/engines` — register a new engine (engine_type, display_name, config, k8s_service_name)
- `GET /api/engines/{id}` — get engine details
- `PUT /api/engines/{id}` — update engine configuration
- `DELETE /api/engines/{id}` — deregister an engine
- `PUT /api/engines/preferences` — set engine preference order (for fallback routing)
- `GET /api/engines/preferences` — get current engine preference order

**Engine Catalog:**
- `GET /api/catalog/engines` — list all catalog entries (default + custom), filterable by engine_type and enabled
- `POST /api/catalog/engines` — add a custom catalog entry
- `GET /api/catalog/engines/{id}` — get a single catalog entry
- `PUT /api/catalog/engines/{id}` — update a custom catalog entry (403 if is_default)
- `DELETE /api/catalog/engines/{id}` — delete a custom catalog entry (403 if is_default)
- `PUT /api/catalog/engines/{id}/toggle` — enable/disable any entry (including defaults)
- `POST /api/catalog/engines/reset` — re-enable all defaults, delete all custom entries

**Data ingestion:**
- `POST /api/ingest/tpcds` — trigger TPC-DS data generation (configurable scale factor)
- `GET /api/ingest/{job_id}` — poll ingestion job status

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

---

## Development Phases

- [x] **Phase 1 - Local Dev Environment:** Minikube cluster, routing-service and web-ui scaffolded, containerized, deployed via K8s manifests
- [x] **Phase 2 - Supporting Infrastructure:** PostgreSQL StatefulSet, DuckDB worker, backend wiring via ConfigMap, correlation_id schema
- [x] **Phase 3 - Service Wiring & System Health:** Health indicators polling every 15s, web-ui ConfigMap
- [x] **Phase 4 - React UI:** Superseded by Phase 5, then revived as Phase 7
- [x] **Phase 5 - Vanilla HTML + jQuery UI:** Single index.html served by FastAPI, no build step, no Node.js. Superseded by Phase 7 React migration.
- [~] **Phase 6 - Databricks Integration (backend only):** Backend complete (tasks 1-6), UI tasks cancelled (tasks 7-13) — jQuery UI work superseded by React migration. Completed: `databricks-sdk` and `kubernetes` dependencies, `admin-credentials` Secret + RBAC manifests, `POST /api/auth/login` with Bearer token middleware, `POST/GET /api/settings/databricks` with K8s Secret persistence, `/health/backends` Databricks status, web-ui proxy routes for auth/settings/warehouses. Not completed (carry forward to Phase 7): `GET /api/databricks/warehouses` and `PUT /api/settings/warehouse` routing-service endpoints, credential reload on startup, all UI components.
- [~] **Phase 7 - React Frontend & Remaining Phase 6 Backend:** React prototype incorporated into web-ui with Vite build pipeline and multi-stage Dockerfile (done). UI restructured per ODQ-8: workspaces in left panel, routing config in right panel Routing tab, collections in right panel Collections tab. Extensive UI redesign completed based on iterative UX feedback (right panel, left panel, center panel — see web-ui module for details). All frontend features use mock data (`src/mocks/api.ts`). Remaining: wire mock API calls to real backend endpoints via fetch wrapper with auth header injection, credential reload on startup, minikube E2E deploy. See taskmaster phase7 tag for detailed task breakdown.

---

## Pending Fixes

Small items that don't warrant their own phase but should be addressed. These are folded into the next active phase or handled as quick standalone tasks.

- [ ] **PostgreSQL schema: add engines table.** The `engines` table (id string PK, engine_type, display_name, config JSONB, k8s_service_name, catalog_id FK nullable, is_temporary bool, benchmark_id FK nullable, is_active, created_at, updated_at) does not yet exist in `routing-service/db/schema.sql`. Add via migration when the first feature needs it (benchmarks or multi-engine routing). Update `benchmark_engine_warmups.engine_id` and `benchmark_results.engine_id` to FK once table exists.
- [ ] **PostgreSQL schema: add engine_preferences table.** The `engine_preferences` table (id, engine_id FK, preference_order int, created_at) does not yet exist. Stores user-defined engine ordering for fallback routing when no ML model is available. Add alongside the engines table.
- [ ] **PostgreSQL schema: add routing_rules table.** The `routing_rules` table (id serial PK, priority int, condition_type text, condition_value text, target_engine text, is_system bool, enabled bool) does not yet exist. Mandatory rules seeded by migration with `is_system = true`. Add when implementing the routing pipeline (ODQ-5).
- [ ] **PostgreSQL schema: add engine_catalog table.** The `engine_catalog` table (id serial PK, engine_type enum, display_name text, config JSONB, is_default bool, enabled bool, created_at, updated_at) does not yet exist. Predefined configs seeded by migration with `is_default = true`. Add when implementing the benchmark lifecycle (ODQ-7).
- [ ] **Routing-service RBAC: extend to Deployments and Services.** The routing-service Role currently only covers Secrets. Extend to include `apiGroups: ["apps"]`, `resources: ["deployments"]`, `verbs: ["get", "create", "delete"]` and `apiGroups: [""]`, `resources: ["services"]`, `verbs: ["get", "create", "delete"]` for temporary DuckDB engine provisioning during benchmarks.

---

## Design Principles

**Cloud-Agnostic Architecture**
- Use Kubernetes instead of cloud-specific managed services
- Abstract cloud-specific connectors behind interfaces
- Reproducible on any cloud or local infrastructure

**Modularity**
- Separate concerns: parsing, metadata retrieval, routing decision, execution
- Pluggable routing strategies (enable/disable features via configuration)
- Run mode toggle in right panel: `single` (one engine selected, query always runs there) or `multi` (multiple engines enabled, routing pipeline decides). In multi mode, the full 4-layer pipeline applies: mandatory hard rules → user-defined rules → ML prediction → fallback to engine preference order. The backend routing API still accepts `routing_mode` (duckdb / databricks / smart) per query for programmatic use.
- Smart Routing uses a layered pipeline (ODQ-5): mandatory hard rules (engine-agnostic access constraints, always applied), user-defined hard rules, ML model prediction, then fallback to engine preference order. Rules stored in `routing_rules` table. Time/cost weights are user-configurable via routing settings.

**Observability-First**
- Log every routing decision with full context (inputs, scores, reasoning)
- Track actual vs estimated costs and latencies
- Enable post-hoc analysis of routing accuracy
- Every query is assigned a `correlation_id` at entry — all logs across all services are joinable by this key

**Cost Optimization**
- Keep one DuckDB worker always warm (eliminate cold starts)
- Use Kubernetes spot nodes for burst capacity (85-90% savings)
- Scale down during idle periods

---


