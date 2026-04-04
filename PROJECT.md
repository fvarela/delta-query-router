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
- ~~Region-awareness: warn the user if DuckDB engine and data are in different regions, which would invalidate benchmark results from same-region runs~~ Addressed by ODQ-9 (storage latency probes make benchmarks portable across regions)
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

### ODQ-9: Network latency measurement and portable benchmarks — DECIDED

**Decision (2026-03-21):** Engine performance is significantly affected by data read time from storage, which varies dramatically based on deployment proximity to data. DuckDB engines read from object storage (ADLS, S3, GCS) directly, while Databricks engines read from Delta tables whose underlying files reside in cloud storage at locations determined by Unity Catalog `storage_location` — neither engine type is co-located with its data. To make benchmark data and ML models portable across deployment locations, the system measures and factors out network I/O latency as a separate, independently measurable component — analogous to how cold-start latency is already handled.

**Design:**
- **Storage latency probe:** A lightweight read operation against a known-size file (or table sample) in each storage location that engines access. For DuckDB engines, this is a direct object-storage read. For Databricks engines, this is a lightweight SQL query (e.g., `SELECT COUNT(*) FROM table LIMIT 1`) executed on the warehouse to measure round-trip I/O from compute to the Delta table's underlying storage. Measures round-trip I/O time from each engine to the storage account/bucket. Run automatically as part of benchmark warm-up and on-demand via API. The exact probing mechanism for Databricks is a future implementation detail — the schema and API support all engine types from the start.
- **Per-storage-location measurement:** Latency is measured per storage location (e.g., `abfss://container@account.dfs.core.windows.net/`, `s3://bucket/prefix/`), not per table. Multiple tables in the same storage location share one measurement.
- **Benchmark normalization:** When training ML models (ODQ-10), the raw benchmark execution time is decomposed as: `total_time = compute_time + io_latency`. The model trains on `compute_time` (total minus measured I/O baseline) so it learns computation cost independent of network location.
- **Prediction-time recomposition:** At routing time, the predicted latency is: `predicted_compute_time (from model) + current_io_latency (from latest probe) + cold_start_latency (if engine is cold)`. Each component is independently measurable and independently reportable.
- **Redeployment workflow:** When the system is deployed to a new location, only the storage latency probes need to be re-run (seconds to minutes). Full benchmarks and model retraining are not required — the existing model's compute-time predictions remain valid.

**Schema:**
- `storage_latency_probes`: id (serial PK), storage_location (text), engine_id (text, FK to engines), probe_time_ms (float), bytes_read (bigint), measured_at (timestamptz)
- Index on `(storage_location, engine_id, measured_at DESC)` for efficient latest-probe lookups

**API:**
- `POST /api/latency-probes/run` — trigger storage latency probes for all active engines (DuckDB and Databricks) and all known storage locations
- `GET /api/latency-probes` — list latest probe results, grouped by storage location and engine
- Probes also run automatically during benchmark warm-up phase (after engine warm-up, before query execution)

**Interaction with benchmarks and models:**
- `benchmark_results` gains an optional `io_latency_ms` column (nullable float) — populated from the latest probe at benchmark time. Allows retrospective computation of `compute_time = execution_time_ms - io_latency_ms`.
- ML model training (ODQ-10) uses `compute_time` as the target variable for the latency model when `io_latency_ms` is available, falling back to raw `execution_time_ms` when it is not.

**UI implications:**
- **Routing tab — Storage Latency section:** A compact section below the Engines table in the right panel Routing tab. Shows latest probe results per storage location in a table (location, latency in ms, timestamp). Latency values color-coded: green (≤50ms), amber (50-150ms), red (>150ms). "Run Probes" button triggers on-demand measurement. Visible whenever Smart Routing mode is active (multiple engines enabled).
- **Benchmark detail — Storage Probes:** When viewing a benchmark detail (click on a benchmark in the Collections tab), a "Storage Latency Probes" section shows the probe results captured at benchmark time. Displays per-location latency measurements that were used to compute `io_latency_ms` for each benchmark result.
- **Benchmark results — I/O decomposition:** When `io_latency_ms` is available on a benchmark result, the execution time cell shows an inline decomposition: `45ms (33+12 I/O)` with a tooltip explaining the breakdown (`compute_time + io_latency`). This makes the I/O component visible without adding extra columns.

### ODQ-10: Latency model and cost tiers — DECIDED (revised 2026-03-27)

**Decision (2026-03-21, revised 2026-03-27):** The single multi-output model from ODQ-3 (predicting both `execution_time_ms` and `cost_usd` in one model) is replaced by a **latency model** for ML-based predictions and **static cost tiers** for cost comparison. Real-dollar cost estimation (per-query USD) was investigated and rejected — Databricks bills by warehouse uptime (not per-query), DBU rates vary by region/cloud/warehouse-type, and the resulting numbers would be misleading. Instead, each engine is assigned a relative cost tier (1–10) that enables fair cost comparison without false precision.

**Supersedes:** ODQ-3 target variables, `models` schema, and `routing_settings` schema. All other ODQ-3 elements (framework, training workflow, activation, features) remain unchanged. Also supersedes the original ODQ-10 cost model concept (formula-based `estimated_cost_usd`, `cost_estimation_mode` toggle, ML cost model).

**Latency model:**
- **Target variable:** `predicted_compute_time_ms` per engine — the computation time excluding I/O latency and cold-start. When `io_latency_ms` is available in benchmark data (ODQ-9), the target is `execution_time_ms - io_latency_ms`. When not available, falls back to raw `execution_time_ms`.
- **At routing time:** Total predicted latency = `predicted_compute_time_ms` + `io_latency_ms` (latest storage probe for the tables in the query, per ODQ-9) + `cold_start_ms` (from `benchmark_engine_warmups` if engine is cold, 0 if warm — see ODQ-11 for how engine state determines this). Each component is logged separately in the routing decision for full transparency.
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
1. For each enabled engine, compute: `latency_score = predicted_compute_time + io_latency + cold_start`
2. For each enabled engine, look up: `cost_score = engine.cost_tier`
3. Normalize both scores across engines (min-max or z-score)
4. Compute weighted score: `score = w_latency * normalized_latency + w_cost * normalized_cost_tier`
5. Select engine with lowest score
6. Weights (`w_latency`, `w_cost`) are user-configurable via the "Speed <-> Cost" toggle (exposed in routing settings)

**Note:** Step 5 is extended by ODQ-11 (engine state awareness) to apply a running-engine bonus before final selection. See ODQ-11 for details.

**Routing without an ML model (rules-only fallback):**
Smart Routing does **not** require an active ML model. The routing pipeline layers are: System Rules → If-Then Rules → ML predictions → Cost vs Latency Priority weighting. Without a model, the first two layers still function — system rules enforce mandatory constraints (e.g., writes to Databricks) and user-defined if-then rules route queries by pattern matching. Only ML-based latency predictions and priority-weighted scoring are skipped. This means the Cost vs Latency Priority toggle has no effect until a model is selected. The UI communicates this clearly: the ML Models section shows "none active" in its header and guidance text in the expanded state; the Cost vs Latency Priority section shows a hint explaining that weighting applies once a model is selected.

**Updated schema (supersedes ODQ-3 schema and original ODQ-10 schema):**
- `engines`: add `cost_tier` (integer, default 5, CHECK 1–10) — relative cost of running queries on this engine.
- `models`: id, linked_engines (JSONB array of engine_id strings), latency_model (JSONB — r_squared float, mae_ms float, model_path text), training_queries (int), is_active (boolean), created_at, updated_at. Models are **latency-only** — no cost sub-model.
- `routing_settings`: id (singleton, always 1), fit_weight (float, default 0.5), cost_weight (float, default 0.5), running_bonus_duckdb (float, default 0.05), running_bonus_databricks (float, default 0.15), updated_at. **Removed:** `cost_estimation_mode` (no longer needed — cost is always a static tier lookup). **Naming rationale:** "fit" means query-engine architectural fit (not actual execution speed) — simple queries score high for DuckDB, complex queries score high for Databricks.
- **Removed:** `cost_metrics` table (no per-query cost data to store).

**UI implications:**
- **Cost vs Fit Priority toggle:** Positioned as a scoring sub-node in the RoutingPipeline timeline diagram in the right panel Routing tab. Only visible in Smart Routing mode (hidden in Single Engine mode). A discrete 3-step toggle with options: "Low Cost" (fit_weight=0.2), "Balanced" (0.5), "High Fit" (0.8). Maps to `fit_weight` and `cost_weight` (they sum to 1.0). Accessible by clicking the "Priority" sub-node in the Scoring section of the timeline.
- **Pipeline stage info:** Each pipeline stage's configuration is accessible by clicking the corresponding node in the RoutingPipeline timeline diagram. The fixed detail area below the diagram shows the selected stage's content. When nothing is selected, the detail area shows a Pipeline Overview with educational content about how the routing pipeline works.
- **ML Models section:** Models are **latency-only** (not bundles). Model cards show the model name, linked engine count, benchmark count, and a "View Details" link. No type badges on the cards. The "View Details" modal shows training metadata (created date, engines, benchmarks, training queries) and latency model metrics (R², MAE in ms, model path). No cost model metrics.
- **Engines section:** Each engine row includes a cost tier indicator (e.g., "$" to "$$$$" or numeric 1–10) alongside the existing type and specs summary. Cost tier is editable in the engine configuration.
- **Query Detail Modal — decomposed routing decision:** Each routing decision shows the decomposed latency breakdown: Compute Time + I/O Latency + Cold Start = Total Latency, with each component on its own line and color-coded. Scoring breakdown shows latency_score, cost_tier, and weighted_score — making it clear why a particular engine was chosen. No "Estimated Cost" line in USD.

---

### ODQ-11: Running Engine Bonus — DECIDED

**Decision (2026-03-21):** After the existing scoring logic (ML predictions + Cost vs Latency Priority) produces a weighted score for each engine, apply a flat **bonus** (score reduction) to engines whose `runtime_state` is `running`. This nudges the router toward already-running engines without replacing or complicating the ML-based scoring.

**Motivation:**
- Starting a stopped Databricks warehouse means waiting for cold-start (30s–5min) *and* committing to a billing period — the warehouse runs (and charges DBUs) until auto-stop.
- A running warehouse processes additional queries with no extra startup delay.
- DuckDB engines are always-on (or scale from zero cheaply), so their bonus is smaller.
- Rather than computing a complex startup penalty from `dbu_rate` and `auto_stop_timeout_minutes`, a simple flat bonus per engine type is more transparent, user-tunable, and equally effective in practice.

**Engine runtime state:**
Each engine has a `runtime_state` tracked at routing time:
- `running` — engine is actively processing or idle but still billed
- `stopped` — engine is not running and would require a cold start
- `starting` — in the process of starting (treated as `stopped` for scoring)
- `unknown` — state cannot be determined (treated as `stopped` conservatively)

For Databricks: polled via `GET /api/2.0/sql/warehouses/{id}` every 30–60s, cached in memory.
For DuckDB: derived from K8s pod status; effectively always `running` in current design.

**Scoring adjustment:**
After the existing ODQ-10 pipeline produces a `weighted_score` per engine:
```
final_score = weighted_score - running_bonus   (if runtime_state === "running")
final_score = weighted_score                   (if stopped / starting / unknown)
```
- `running_bonus_duckdb` — default **0.05** (small; DuckDB is cheap and always-on, so the bonus rarely matters)
- `running_bonus_databricks` — default **0.15** (larger; reflects the significant cost/latency savings of routing to an already-running warehouse)
- Both values are **user-editable** in the UI via the "Running Engine Bonus" section.
- Setting a bonus to **0** effectively disables it for that engine type.
- A "Reset to Defaults" button restores both to their default values.

**Design constraints:**
- **Flat and simple.** No formula, no per-engine parameters. Just two numbers.
- **Self-correcting.** Once a warehouse is running, subsequent queries naturally prefer it. Once it stops, the bonus no longer applies.
- **User-tunable.** Advanced users can increase or decrease the bonus. Setting to 0 disables it — no separate on/off toggle needed.
- **Applied last.** The bonus runs after ML scoring and Cost vs Latency Priority, before the final engine selection. It does not interfere with system rules or hard rules (those short-circuit before scoring).

**Parameters added:**
- `runtime_state` per engine (ephemeral, in-memory cache — not persisted in PostgreSQL).
- `running_bonus_duckdb` in `routing_settings` (float, default 0.05).
- `running_bonus_databricks` in `routing_settings` (float, default 0.15).

**UI implications:**
- **Engines table:** Show engine runtime state as a status dot (green = running, gray = stopped, amber = starting).
- **Running Engine Bonus scoring sub-node:** Shown in the RoutingPipeline timeline as a sub-node under Scoring & Select, between Priority and Storage. Status shows current bonus values (e.g., "0.05/0.15"). Click to open detail panel with explanatory text, two editable numeric inputs, and a "Reset to Defaults" button.
- **Routing decision log:** Include bonus application in log output when applicable.

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
- **Input features (available pre-execution):** AST features from `query_analyzer.py` (complexity_score, join_count, agg_count, subquery_count, window_function_count, table_count, statement_type) + table metadata from catalog cache (size_bytes, data_source_format, table_type, has_rls, has_column_masking, external_engine_read_support) + storage latency from probes (io_latency_ms per storage location, per ODQ-9).
- **Output (prediction target):** `execution_time_ms` per engine.
- **Cost:** NOT predicted by ML. Handled via static engine cost tiers (1–10 scale, per ODQ-10). The router combines predicted latency + cost tier + running state (ODQ-11) for final decision.

**What benchmarks capture:**
- `(query_text, AST_features, table_metadata, engine_id) → execution_time_ms` — this is the training row.
- **Cold-start captured separately** in `benchmark_engine_warmups` — not mixed into training data. At prediction time, cold-start overhead is added on top of the model's warm-execution prediction.
- **Storage probes included** — I/O latency CAN be measured pre-execution via periodic probing (ODQ-9) and used as a model feature. This is the one "execution-adjacent" metric that transfers to inference time because it captures data locality, not query characteristics.

**What benchmarks skip:**
- `data_scanned_bytes`, `peak_memory_bytes`, `credential_vending_ms` — not available at inference time.
- Databricks Query History API — deferred. Wall-clock time (including network round-trip) is the target metric because that's what the user experiences. Server-reported execution time could theoretically make training targets more accurate but adds API complexity.

**Two-tier metrics strategy:**
- **Exhaustive tier (benchmarks):** Full AST features + table metadata + execution_time_ms + cold-start + storage probes. Used for ML model training.
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

**Tech Stack:** Python, FastAPI, sqlglot, databricks-sdk, deltalake-python, scikit-learn, PostgreSQL client, kubernetes (Python client for K8s API — engine registration, DuckDB deployment management)

### web-ui (Dashboard)
**Purpose:** Convenience interface for configuring the system, submitting queries, browsing Unity Catalog, managing query collections, and viewing results. The UI is not required — all functionality is exposed via the routing-service API for programmatic use by external services.  
**Status:** Phase 6 backend complete (auth, Databricks credentials, health). React frontend implemented with mock data and extensively redesigned through iterative UX feedback sessions (right panel routing config, left panel workspaces, center panel query editor/results/history). Phase 7 UI redesign complete, including ODQ-9 (storage latency probes UI), ODQ-10 (latency model + cost tiers — discrete Cost vs Latency Priority toggle, decomposed latency in query detail modal), ODQ-11 (Running Engine Bonus). UX Rounds 1-8 complete. **Pipeline redesigned twice:** First replaced separate collapsible sections + info modals with a unified button-accordion layout; then redesigned again into a **compact vertical timeline diagram** with a **fixed detail area** below. The timeline has 4 main nodes (System Rules → If-Then Rules → ML Models → Scoring & Select) with Scoring sub-nodes (Priority, Bonus, Storage) shown as indented items. Default detail area shows a Pipeline Overview with educational content (replacing deleted info modals). All content consolidated into `RoutingPipeline.tsx`. **Layout reorganization (Round 9):** Workspaces collapsed into a compact header with expand-on-click dropdown; Collections/Benchmarks moved from right panel to left panel as a tab alongside Catalog Browser; right panel simplified to routing-only (no tabs); "Add to Collection" button added to center panel action bar. **Phase 8-9:** Query execution, routing rules, catalog browsing, and Databricks credential flows wired to real backend. **Phase 10:** Collections, engines, benchmarks, and storage probes wired to real backend — replaced mock API calls in `src/mocks/api.ts`. **Remaining mocks:** workspaces (multi-workspace management), ML models (training wizard, model activation), routing pipeline stage interactions. **ODQ-13 cleanup pending:** StorageAccountsManager component, storage access indicators in catalog browser, and service principal credential modal (all ODQ-12 mock UI) to be removed — credential vending replaces service principal approach.

**Architecture:** FastAPI backend (server.py) serves Vite-built static assets (index.html + JS/CSS bundles in static/assets/). React source lives in web-ui/frontend/ (development only — not included in production image). The Dockerfile uses a multi-stage build: Node stage runs `npm run build` to produce static assets, Python stage copies the build output and runs FastAPI/uvicorn. Everything is a single-page React app. Most API domains (query execution, routing rules, collections, engines, benchmarks, probes, catalog browsing, auth) are wired to real backend endpoints. Remaining mock domains: workspaces (multi-workspace management) and ML models (training, activation).

**Single-Page Layout:**

**Top bar:** "Delta Router" header. Health indicators and Settings modal are not yet implemented — deferred per ODQ-8.

**Left panel — Workspaces + Catalog/Collections tabs (20% width):**
- **Workspaces (collapsible header, top):** A compact single-line header showing a status dot (green = connected, gray = not connected), "Workspaces" label, and the connected workspace name (or "Not connected"). Clicking the header expands a dropdown showing all workspaces with full management controls: PAT token modal (Key icon), connect/disconnect, delete, and "Add workspace" inline form. Clicking outside or clicking the header again collapses it. The collapsed state saves vertical space since workspaces are rarely changed after initial setup.
- **Tabs: Catalog | Collections:** Two tabs below the workspaces header control which content fills the rest of the left panel. Only one is active at a time.
- **Catalog tab (default):** Headed with "Catalog Browser" title and blue Database icon. Tree navigation: catalogs → schemas → tables. Clicking a table shows its details (type, format, size, external access flags, columns). "Load Sample Query" button populates editor with `SELECT * FROM catalog.schema.table LIMIT 100`. Three-color indicator bar system shows table accessibility: green = DuckDB-readable (Delta or Iceberg format with external access flags set), amber = Databricks-only (native format but governance-blocked, or VIEWs), red = foreign/federated tables (SQL Server, Snowflake, etc. — always Databricks-only). The `data_source_format` field is displayed in the table detail view; foreign formats show in red text with a "Foreign table (Databricks only)" message. Only active when a workspace is connected — otherwise shows "Connect to a workspace to browse catalogs."
- **Collections tab:** Shows query collections list with query counts and descriptions. Clicking opens collection detail: ordered query list (click to load into editor), "Run Benchmark" button, benchmark history. See "Benchmarks" section below for full benchmark workflow. **"Add to Collection" workflow:** When a collection is open and the SQL editor has content, the center panel action bar shows an "Add to Collection" button. Clicking it adds the current editor SQL as a new query to the active collection. Brief "Added!" confirmation is shown.

**Center panel — Query Editor + Results + Query History (50% width):**
- **Query Editor (fixed top):** SQL textarea for writing and editing queries. Action bar contains: "Run" button (disabled when no query entered), and an "Add to Collection" button (visible only when a collection is open in the left panel and the editor has content). The "Add to Collection" button adds the current SQL to the active collection and shows a brief "Added!" confirmation.
- **Results area (fixed, non-scrollable):** Shows execution metrics (engine, latency, rows) and a data table limited to 10 rows maximum. No routing decision details here — those live in the query detail modal.
- **Query History (scrollable, takes remaining space):** The only scrollable area in the center panel. Sticky table header. Rows show timestamp, query preview, engine, status badge, and latency. Completed rows are clickable (`cursor-pointer` + hover highlight); running rows are not clickable. No "Details" button column.
- **Query Detail Modal:** Opens when clicking a completed history row. Contains: header with full query text + close button (X), summary row (timestamp, engine, status badge, latency), Routing Decision in a grid layout (Engine, Stage, Reason, Complexity), decomposed latency breakdown when available (Compute Time + I/O Latency + Cold Start = Total Latency, each on its own line with color coding), scoring breakdown (latency_score, cost_tier, weighted_score), and a Routing Log in dark terminal-style display showing color-coded streaming events by level (info/rule/decision/warn/error) and stage ([PARSE]/[RULES]/[ML]/[ENGINE]/[EXEC]/[DONE]). Closes on backdrop click, close button, or Escape key.

**Right panel — Routing (30% width):**
Dedicated to routing configuration — no tabs (collections moved to left panel).

*Sections listed in display order:*
- **Engines section (always expanded):** Header with Server icon and parenthetical "(No Databricks workspace)" when no workspace is connected. Contains a passive mode indicator showing "Single Engine" or "Smart Routing" badges based on how many engines are enabled — no toggle button. Table layout with columns: checkbox | Type | Specs summary. Always checkboxes (no radio buttons). Databricks engines shown only when a workspace is connected. Single engine triggers "Single Engine" mode; multiple engines trigger "Smart Routing" mode. When in Single Engine mode (or no engines), a guidance message is shown below the table explaining how to enable Smart Routing. **Engine runtime state (ODQ-11):** Each engine row shows a status dot (green = running, gray = stopped, amber = starting) reflecting real-time engine state from the Databricks API / K8s pod status. This gives users visibility into which engines are active and helps explain why the router may prefer one engine over another.
- **Unified Routing Pipeline (`RoutingPipeline.tsx`):** A compact **vertical timeline diagram** with a **fixed detail area** below. The timeline uses a continuous vertical line with color-coded dots (green/amber/gray) connecting 4 main nodes: **System Rules → If-Then Rules → ML Models → Scoring & Select → ▸ Selected Engine**. The "Scoring & Select" node has 3 indented sub-nodes (Priority, Bonus, Storage) shown under it with a dashed connector, reflecting that they are parameters to the scoring step rather than independent sequential stages. Each node shows an icon, label, and inline status text (e.g., "2 rules", "0/2", "Balanced"). Clicking any node or sub-node opens its detail/config in the **fixed detail area** below the diagram. The detail area has a header (title + close X button) and scrollable content. When no node is selected, the detail area shows a **Pipeline Overview** — a summary of routing status with educational text explaining how the pipeline works (replaces the old info modals). Only visible in Smart Routing mode (multi-engine). Deleted files: `RoutingInfoModal.tsx`, `RoutingPipelineSummary.tsx`, `RoutingFlowModal.tsx`, `RunModeSelector.tsx`, `SystemRules.tsx`, `HardRules.tsx`, `MLModelSelector.tsx`, `SpeedCostSlider.tsx`, `RunningEngineBonus.tsx`, `StorageLatencySection.tsx`. All content consolidated into `RoutingPipeline.tsx`.
- **System Rules (timeline node):** Status shows rule count. Detail panel shows explanatory text about mandatory constraints, then each system rule as a read-only line (e.g., "Table type = VIEW → Databricks").
- **If-Then Rules (timeline node):** Status shows custom rule count. Detail panel shows explanatory text, rules inline, and "Edit Rules..." button that opens the full rule management modal (add/edit/delete, move up/down priority).
- **ML Models (timeline node):** Status shows "Active" when a compatible model is active, "X/Y" (compatible/total) when models exist but none active, or "None" when no models. Detail panel shows explanatory text, model cards with radio-button activation (disabled when incompatible), compatibility check, delete button per model. Models are **latency-only** (no cost sub-model). Cards show model name, engine count, benchmark count, and "View Details" link that opens a modal with training metadata and latency model metrics (R², MAE in ms, model path). No type badges on cards. **Guidance text** appears below the model list when no model is active. **"Train New Model..." button** at the bottom opens the 4-step train wizard. **Compatibility rule:** enabled_engines ⊆ model.linked_engines. Databricks engines excluded from compatibility checks when no workspace connected.
- **Scoring & Select (timeline node):** Status shows priority label (always active — uses heuristic scoring even without ML model). Detail panel shows overview of all scoring parameters (priority split, bonus values, storage probe count) with a note to click sub-nodes for configuration. When no ML model active, explains scoring uses complexity-based heuristic.
- **Cost vs Fit Priority (scoring sub-node):** Detail panel shows explanatory text and discrete 3-step toggle: "Low Cost" | "Balanced" | "High Fit", mapping to `fit_weight` / `cost_weight`. Cost scores: DuckDB=0.7 (cheap, no per-query cost), Databricks=0.2 (pay-per-query). Fit scores: complexity-based heuristic measuring query-engine architectural fit (DuckDB excels at simple queries, Databricks at complex ones) — not actual execution speed. When no ML model active, shows note about heuristic scoring.
- **Running Engine Bonus (scoring sub-node):** Detail panel shows explanatory text and two editable numeric inputs (DuckDB bonus, Databricks bonus) with "Reset to Defaults" button.
- **Storage Latency (scoring sub-node):** Always shown in Smart Routing mode (applies to all engine types — both DuckDB and Databricks read from cloud storage). Detail panel shows explanatory text, "Run Probes" button, probe results table (location, latency, bytes read, timestamp) with color-coded latency.

**Collection data model:** See ODQ-1 for schema. Collections are purely groups of queries — no routing mode stored. All saved queries belong to a collection.

**Benchmarks** (accessible when a collection is open in the Collections tab):
- "Run Benchmark" button with progress stages (Provisioning engines → Warming up → Running queries → Cleaning up → Complete)
- Benchmark history list showing past runs per collection
- Clicking a benchmark shows details: warm-up times per engine, **transposed results matrix** (engines as rows × queries as "Q1, Q2..." columns) with color highlighting for best/worst times per query. Engine name column is sticky for horizontal scroll. I/O breakdown available on hover.

**Train wizard** (opens from "Train New Model..." button in ML Models pipeline stage detail panel):
- **Step 1 — Select Engines:** Checkbox table of all engines (same as Routing tab engines). At least 2 required. Databricks engines provisioned ephemerally if no workspace connected.
- **Step 2 — Select Query Collections:** Multi-select checkboxes (none, one, or many). Each selected collection has a configurable run count (1–10) via +/- stepper. Summary shows total collections and total runs.
- **Step 3 — Include Past Benchmarks:** Checkbox list of all completed historical benchmark runs across all collections. Each shows collection name, run ID, date, and engine count. Optional — enriches training data with known-good historical results.
- **Step 4 — Existing Models:** Read-only reference showing current models with compatibility status against selected engines.
- **Training action:** Summary of total training data sources (new runs + historical benchmarks). "Start Training" button requires >= 2 engines and >= 1 data source (either new runs or past benchmarks). Progress stages: Provisioning → Running benchmarks → Loading historical data → Collecting metrics → Training → Validating.

**Model lifecycle:** Models are latency-only and can be activated (radio), deactivated, expanded for details, and deleted (trash icon). Deleting an active model deactivates it first.

**State management:** Global AppContext provides: editor state (SQL, results, collection context), workspaces (list + connected workspace), engines (catalog entries, enabled IDs, cost tiers), routing mode (derived from engine count — Single Engine vs Smart Routing), routing settings (fit_weight, cost_weight — loaded from API, updated via toggle), storage probes (latest probe results, probesRunning flag, runStorageProbes action), models (list + active model ID), query history (with per-query routing events and decisions), panel mode (run/train for the right panel train wizard). All data loaded from mock API on mount.

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

### delta-router-sdk (Python SDK)
**Purpose:** Pip-installable Python client providing DB-API 2.0 compatible interface for end users to submit queries through Delta Router with minimal code changes from `databricks-sql-connector`  
**Status:** Not started (designed in ODQ-15)  
**Requirements:**
- DB-API 2.0 interface: `connect()`, `cursor()`, `execute()`, `fetchall()`, `fetchone()`, `fetchmany()`, `description`
- Authentication via Databricks PAT + workspace URL, transparent token refresh on 401
- Routing overrides via `engine` parameter on `execute()`
- Routing decision introspection via `cursor.routing_decision`
- Engine listing via `conn.list_engines()`

**Tech Stack:** Python, httpx (or requests)

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
- `GET /api/routing/settings` — get routing settings (latency/cost weights, running engine bonuses)
- `PUT /api/routing/settings` — update routing settings (latency/cost weights, running engine bonuses)

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

**Storage Latency Probes:**
- `POST /api/latency-probes/run` — trigger storage latency probes for all active engines (DuckDB and Databricks) and known storage locations
- `GET /api/latency-probes` — list latest probe results, grouped by storage location and engine

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

---

## Exploratory Ideas

Speculative concepts worth capturing but with no timeline or commitment. Unlike Future Considerations (concrete integration plans) or Pending Fixes (actionable items), these are open-ended explorations that may or may not materialize.

- [ ] **Remote DuckDB workers deployed near data (2026-03-27)** — **Partially addressed by Phase 11** (AKS deployment co-locates workers with data in the same Azure region). The remaining idea is about workers deployed *outside* the cluster for even more flexibility — e.g., as Azure Container Apps in different regions than the AKS cluster. The current architecture deploys DuckDB workers inside the same K8s cluster as the routing-service and web-ui. Since DuckDB's value is reading directly from cloud storage (ADLS, S3), network latency between worker and storage dominates query time. The idea: allow DuckDB workers to be deployed *outside* the cluster, close to the data — e.g., as an Azure Container App in the same region as the storage account. The routing-service already talks to duckdb-worker over HTTP (`POST /query`), so the transport is location-agnostic. **What this would involve:** (1) A worker registry replacing the single hardcoded endpoint — each worker with a name, URL, region, health status, and tags indicating which storage it's near. (2) A standalone, self-contained DuckDB worker Docker image that can run anywhere (not just K8s), with its own auth and health reporting back to the control plane. (3) Azure deployment tooling (IaC or `az` CLI scripts) to easily spin up a worker in a target region, tagged with a convention (e.g., `delta-router:worker`) for discovery. (4) Cloud authentication — the system would need Azure credentials (service principal or user login) to discover/manage remote resources, and the remote workers need their own auth (mTLS, shared secrets, or managed identity) plus storage credentials. (5) Auto-discovery of tagged resources in an Azure subscription, or as a simpler first step, manual registration ("here's my worker URL and API key"). (6) A second routing decision layer: not just *which engine* but *which worker instance*, factoring in worker location vs. data location. **Key tradeoffs:** Results still travel back to the routing-service over the network, so large result sets could negate the benefit — but for the common case (small results from big data), the win is clear. Trust boundary changes when workers are external. Could start Azure-only or design cloud-agnostic from the start. Container Apps is a better fit than Functions (avoids cold starts and execution time limits). **Implementation effort estimate:** Layers 1–2 (worker registry with URL support + standalone worker image with API key auth) are small and align with ODQ-4 engine registry work — the duckdb-worker is already a self-contained FastAPI service. Layer 3 (Azure deployment tooling — Bicep/Terraform for Container Apps) is a focused IaC chunk. Layer 4 (auto-discovery + cloud auth for scanning subscriptions) is the only genuinely complex part and is fully deferrable — manual registration covers the use case. **When to revisit:** When building the engine registry (ODQ-4), design it with `endpoint_url` support from the start so remote workers slot in naturally later. **Related idea considered and deferred:** Distributed query decomposition across multiple DuckDB workers (each handling a portion of a join where tables live in different storage accounts, then merging partial results). This is essentially building a distributed query engine on top of single-node DuckDB — what Spark/Trino do — and is a massive engineering effort. Not worth pursuing; cross-location joins should route to Databricks instead.

---

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
- [ ] **Phase 13 - ML Model Training Pipeline:** Train latency prediction models from benchmark data and integrate them into the routing pipeline (ODQ-3/ODQ-10). **Backend:** `models` table (latency-only per ODQ-10), extended query feature extraction, `POST /api/models/train` (scikit-learn RandomForest, hold-out validation, joblib serialization), model activation/deactivation endpoints, `GET/DELETE /api/models` CRUD. Populate `io_latency_ms` in benchmark results from storage probes at benchmark time. ML inference at routing time: load active model → predict `compute_time_ms` per engine → combine with `io_latency` + `cold_start` + cost tier → weighted score → engine selection. Engine state polling (ODQ-11): periodic Databricks warehouse state + K8s pod status checks, `runtime_state` caching, running engine bonus in scoring. **Frontend:** Wire ML Models section (replace mocks) — model list, train button, activate/deactivate, detail view with metrics. **Testing:** Feature extraction tests, training pipeline tests, inference tests, model API endpoint tests. PRD: `.taskmaster/docs/phase13-ml-model-training.md`.

---

## Pending Fixes

Small items that don't warrant their own phase but should be addressed. These are folded into the next active phase or handled as quick standalone tasks.

- [x] **PostgreSQL schema: add engines table.** *(Created in Phase 10, Task 35. Simplified vs. original spec: no catalog_id FK, no is_temporary, no benchmark_id FK — those are deferred to the engine catalog/managed benchmark lifecycle ODQ-7.)*
- [x] **PostgreSQL schema: drop cost_metrics table.** The `cost_metrics` table stores per-query `estimated_cost_usd` which is no longer computed (cost is now a static engine property via cost tiers). Drop the table and its index. Remove the `cost_metrics` INSERT from `query_logger.py`. *(Folded into Phase 9, Task 22.)*
- [x] **PostgreSQL schema: drop cost_estimation_mode from routing_settings.** The `cost_estimation_mode` column is no longer needed — cost is always a static tier lookup from the engine record. Remove from schema and API. *(Folded into Phase 9, Task 22.)*
- [x] **PostgreSQL schema: add engine_preferences table.** *(Created in Phase 10, Task 35.)*
- [x] **PostgreSQL schema: add routing_rules table.** The `routing_rules` table (id serial PK, priority int, condition_type text, condition_value text, target_engine text, is_system bool, enabled bool) does not yet exist. Mandatory rules seeded by migration with `is_system = true`. Add when implementing the routing pipeline (ODQ-5). *(Folded into Phase 8, Task 1.)*
- [ ] **PostgreSQL schema: add engine_catalog table.** The `engine_catalog` table (id serial PK, engine_type enum, display_name text, config JSONB, is_default bool, enabled bool, created_at, updated_at) does not yet exist. Predefined configs seeded by migration with `is_default = true`. Add when implementing the benchmark lifecycle (ODQ-7).
- [ ] **Routing-service RBAC: extend to Deployments and Services.** The routing-service Role currently only covers Secrets. Extend to include `apiGroups: ["apps"]`, `resources: ["deployments"]`, `verbs: ["get", "create", "delete"]` and `apiGroups: [""]`, `resources: ["services"]`, `verbs: ["get", "create", "delete"]` for temporary DuckDB engine provisioning during benchmarks.
- [x] **PostgreSQL schema: add storage_latency_probes table.** *(Created in Phase 10, Task 35.)*
- [ ] **PostgreSQL schema: update models table for latency-only architecture.** The `models` table stores latency-only models (no cost sub-model). Remove the `model_type` column and `model_path`/`accuracy_metrics` top-level fields. Add `latency_model` JSONB (r_squared, mae_ms, model_path) and `training_queries` int. No `cost_model` field. Update when implementing the model training pipeline.
- [ ] **PostgreSQL schema: add io_latency_ms to benchmark_results.** Per ODQ-9, the `benchmark_results` table needs an optional `io_latency_ms` column (float, nullable) populated from the latest storage latency probe at benchmark time. Allows computing `compute_time = execution_time_ms - io_latency_ms` for model training.
- [x] **PostgreSQL schema: update routing_settings for ODQ-10.** Rename `time_weight` to `latency_weight`, keep `cost_weight`. Remove `cost_estimation_mode` column (cost is now a static engine property via cost tiers, not a per-query estimation). *(Folded into Phase 8, Task 1. `cost_estimation_mode` removal pending — currently in schema but should be dropped.)*
- [x] **Catalog browser: display data_source_format for all tables.** Show the `data_source_format` field (DELTA, ICEBERG, PARQUET, SQLSERVER, SNOWFLAKE, etc.) in the table detail view. Foreign/federated tables should show a distinct red indicator alongside the existing green (DuckDB-readable) and amber (Databricks-only) indicators. *(Done — implemented in Phase 7 ODQ-9/ODQ-10 UI work with three-color bar system: green/amber/red.)*
- [ ] **DuckDB worker: install Iceberg extension and add ICEBERG to routing fallback.** The duckdb-worker currently only installs the httpfs extension (delta extension no longer loaded — parquet files are read via httpfs with signed URLs). DuckDB supports Iceberg via a core extension (`INSTALL iceberg; LOAD iceberg;` — see [DuckDB Iceberg docs](https://duckdb.org/docs/stable/core_extensions/iceberg/overview.html)). Iceberg support would require a parallel reader path in `credential_vending.py`. Until then, Iceberg tables route to Databricks.
- [ ] **Routing rules: add foreign/federated table test cases.** Add test cases for routing decisions involving foreign/federated tables (SQL Server, Snowflake, etc. registered via Lakehouse Federation). These tables must always route to Databricks — verify that the existing external access check correctly handles them (no `storage_location`, no `HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT`).
- [ ] **Engines config JSONB: add runtime_state tracking.** Per ODQ-11, engine `runtime_state` (`running` / `stopped` / `starting` / `unknown`) is polled and cached in memory. Not persisted in PostgreSQL — this is ephemeral operational state.
- [ ] **Routing-service: engine state polling.** Per ODQ-11, implement periodic polling (every 30–60s) of Databricks warehouse state via `GET /api/2.0/sql/warehouses/{id}` and K8s pod status for DuckDB engines. Cache `runtime_state` in memory. Used by the routing algorithm to apply the running engine bonus.
- [x] **PostgreSQL schema: update routing_settings for ODQ-11.** Add `running_bonus_duckdb` (float, default 0.05) and `running_bonus_databricks` (float, default 0.15) to `routing_settings`. *(Folded into Phase 8, Task 1.)*
- [x] ~~**PostgreSQL schema: add storage_account_status table.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).
- [x] ~~**K8s Secret: add azure-storage-credentials manifest.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).
- [x] ~~**Routing rules: add storage account inaccessibility system rule.**~~ Cancelled — ODQ-12 retired per ODQ-13 (credential vending).

---

## Design Principles

**Cloud-Agnostic Architecture**
- Use Kubernetes instead of cloud-specific managed services
- Abstract cloud-specific connectors behind interfaces
- Reproducible on any cloud or local infrastructure

**Modularity**
- Separate concerns: parsing, metadata retrieval, routing decision, execution
- Pluggable routing strategies (enable/disable features via configuration)
- Run mode indicator in right panel Engines section: `Single Engine` (one engine selected, query always runs there) or `Smart Routing` (multiple engines enabled, routing pipeline decides). In multi mode, the full 4-layer pipeline applies: mandatory hard rules → user-defined rules → ML prediction → fallback to engine preference order. The backend routing API still accepts `routing_mode` (duckdb / databricks / smart) per query for programmatic use.
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
- Apply a flat running-engine bonus (score reduction) to engines that are already running — nudges the router toward them without complex penalty formulas (ODQ-11)
- Bonus values are user-tunable per engine type (DuckDB, Databricks) with sensible defaults; setting to 0 effectively disables (ODQ-11)

---


