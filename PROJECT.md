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

## Architecture

### Execution Engines

**Databricks SQL Warehouse**
- Purpose: Handle complex queries, large-scale aggregations, and all queries requiring governance
- Rationale: Required for row-level security and column masking; already available in the infrastructure; powerful for distributed workloads

**DuckDB (Containerized)**
- Purpose: Execute simple queries on small to medium datasets without governance constraints
- Rationale: Extremely fast for OLAP queries on columnar data; native Delta Lake support; runs efficiently in single-node containers; 10-50x cheaper than warehouse for eligible queries
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

**Vanilla HTML + jQuery (Web UI)**
- Purpose: Minimal single-page dashboard for system health, query submission, and observability
- Rationale: Zero build step; no Node.js dependency; jQuery loaded from CDN; FastAPI serves a single index.html as a static file; setInterval + fetch for polling — simpler than any framework for this use case

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

### Observability

**PostgreSQL-Based Metrics Store**
- Purpose: Centralized logging of all query executions, routing decisions, and cost calculations
- Rationale: Single source of truth for evaluation; enables complex analytical queries for dashboards; supports A/B testing between routing strategies

**Web UI Dashboard**
- Purpose: Real-time visualization of cost savings, latency distributions, and routing accuracy
- Rationale: Single-page vanilla HTML dashboard served by FastAPI; lightweight and sufficient for development and demos

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

**Tech Stack:** Python, FastAPI, sqlglot, databricks-sdk, deltalake-python, PostgreSQL client

### web-ui (Dashboard)
**Purpose:** Convenience interface for configuring the system, submitting queries, browsing Unity Catalog, managing query collections, and viewing results. The UI is not required — all functionality is exposed via the routing-service API for programmatic use by external services.  
**Status:** System Health indicators deployed (Phase 5 vanilla HTML)

**Architecture:** FastAPI backend (server.py) serves a single static index.html file. The frontend uses plain HTML, CSS, and jQuery (loaded from CDN). No build step, no Node.js, no framework. Everything lives on a single page.

**Single-Page Layout:**

**Top bar:** Health indicators (colored dots: green/red/grey) for Web UI, Routing Service, PostgreSQL, DuckDB Worker, Databricks. Databricks shows grey 'Not Configured' until credentials are saved. Polls /api/health/services every 15 seconds. A "Settings" text link/button sits next to the health indicators and opens a modal dialog.

**Settings modal:**
- Databricks connection: workspace URL + PAT, or workspace URL + client ID + client secret (service principal)
- User enters credentials; backend validates them, writes to K8s Secret, reinitializes the SDK client
- SQL Warehouse selector: after connecting, lists available warehouses; user selects which one to use
- Access requires admin login (see Authentication section)

**Left panel — Unity Catalog Browser:**
- Tree navigation: catalogs → schemas → tables
- Clicking a table shows its details (type, format, size, external access flags, columns if available)
- "Load sample query" button populates the editor with `SELECT * FROM catalog.schema.table LIMIT 1`
- Indicates which tables DuckDB can read (external engine flags) vs which must go to Databricks

**Center — Query Editor:**
- SQL textarea for writing and editing queries
- Routing mode toggle above the textarea: three-state selector (DuckDB / Databricks / Smart Router). This is a page-level setting — it applies to whatever query or collection is run next
- "Run" button to execute the current query
- "Add to Collection" button — enabled when the editor contains a query not in the currently open collection; lets the user pick an existing collection or create a new one
- Results area below the editor: routing decision trace (engine chosen, complexity score, reason), execution time, estimated cost / cost savings

**Right panel — Collections:**
- List of saved collections. TPC-DS is a pre-built collection
- Clicking a collection opens it: shows the collection name and its ordered list of queries (numbered sequentially)
- Opening a collection sets the page-level routing mode toggle to the collection’s saved routing mode (user can change it freely)
- Each query in the collection has a checkbox for selection
- Clicking a query (not the checkbox) loads its SQL into the editor for viewing/editing/running
- Selection order is tracked and displayed near the action buttons as "current selection: 3, 1, 7"
- Action buttons on the collection:
  - "Run All" — always available; runs all queries in default sequence using the current routing mode toggle
  - "Run Selected" — enabled when ≥1 queries selected; runs them in selection order
  - "Edit Query" — enabled when exactly 1 query selected; loads it in the editor for editing
  - "Delete Query" / "Delete Selected" — with confirmation dialog
- Saving a collection captures the current state of the routing mode toggle

**Collection data model:**
- A collection has: name, routing_mode (`duckdb` / `databricks` / `smart`), ordered list of queries
- Each query in a collection stores: SQL text, sequence number
- Routing mode is stored at the collection level, not per query
- All queries — whether favorites or benchmarks — must belong to a collection. There are no standalone saved queries outside of collections. A "favorite" is simply a collection with one query.
- Collections are stored in PostgreSQL

**Query Log** (below results or as a collapsible section):
- Recent query history table fetched from routing-service API
- Shows engine, status, latency, cost per query

**Tech Stack:** FastAPI (Python), HTML, CSS, jQuery (CDN)

### benchmark-runner (Evaluation)
**Purpose:** Execute query collections as benchmarks and measure routing performance  
**Status:** Not started  
**Requirements:**
- A benchmark run executes a collection (or a selection of queries within a collection) using the routing-service API
- TPC-DS is a pre-built collection with 99 queries, loaded during data-populator setup
- The routing mode for a benchmark run comes from the collection’s saved routing_mode (or the current page toggle if overridden by the user)
- Measure and log latency, cost, and routing decision for every query
- Generate comparison reports when the same collection is run with different routing modes
- Triggered from the web-ui Collections panel or via API
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
    databricks.tf     # new workspace, SQL Warehouse, schemas, governance rules
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
- `POST /api/query` — submit SQL with `routing_mode` (duckdb / databricks / smart) and optional `routing_params`
- `GET /api/query/{correlation_id}` — retrieve past query result and routing decision

**Collections:**
- `POST /api/collections` — create a collection (name, routing_mode, queries)
- `GET /api/collections` — list all collections
- `GET /api/collections/{id}` — get collection with all queries
- `PUT /api/collections/{id}` — update collection metadata
- `DELETE /api/collections/{id}` — delete collection
- `POST /api/collections/{id}/queries` — add query to collection
- `PUT /api/collections/{id}/queries/{query_id}` — update a query
- `DELETE /api/collections/{id}/queries/{query_id}` — remove a query
- `POST /api/collections/{id}/run` — run collection (all or selected queries, with routing_mode)
- `GET /api/collections/runs/{run_id}` — poll run status and results

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

- [x] **Phase 1 - Local Dev Environment:** Minikube cluster, FastAPI routing-service and Streamlit web-ui scaffolded, containerized with Docker using uv, deployed to Kubernetes with manifests, accessible via port-forward
- [x] **Phase 2 - Supporting Infrastructure:** PostgreSQL deployed as StatefulSet with persistent storage and database schema (query_logs, routing_decisions, cost_metrics, table_metadata_cache); DuckDB worker built as FastAPI app and deployed; routing-service wired to both backends via ConfigMap; correlation_id/user_id schema migration applied; all 4 services running and verified in cluster
- [x] **Phase 3 - Service Wiring & System Health:** Build web-ui System Health page with green/red indicators polling every 15 seconds; add web-ui ConfigMap with ROUTING_SERVICE_URL; rebuild and redeploy web-ui image. Deliverable: browser shows live health dashboard with all 4 services green.
- [x] **Phase 4 - Migrate Web UI to React + FastAPI:** Replace Streamlit with Vite + React + TypeScript frontend served by FastAPI as static files. Implement full UI shell: left sidebar navigation, logo placeholder top-center, theme TBD. System Health page with five service indicators (Web UI, Routing Service, PostgreSQL, DuckDB Worker, Databricks), where Databricks shows a grey 'Not Configured' state until integrated. All other pages show [ COMING SOON ] placeholders. Remove Streamlit dependencies, update Dockerfile, redeploy. Deliverable: same System Health functionality as Phase 3 running in React, with the complete navigation shell in place for all future pages.
- [x] **Phase 5 - Simplify Web UI to Vanilla HTML + jQuery:** Replace React + Vite frontend with a single static index.html using plain HTML, CSS, and jQuery (CDN). Remove frontend/ directory, Node.js dependency, and multi-stage Docker build. Revert to single-stage Python Dockerfile. Keep FastAPI server.py and /api/health/services endpoint unchanged. Implement System Health indicators as colored dots with plain text labels on a single page — no sidebar, no routing, no framework. Remove Node.js 20+ from dev prerequisites. Also includes pending fixes: add `collections` and `collection_queries` tables to PostgreSQL schema, update routing-service module status, fix data-populator trigger reference. Deliverable: same health indicator functionality as Phase 4, served from a single HTML file with no build step, plus schema and doc consistency fixes.
- [ ] **Phase 6 - Databricks Integration & Settings UI:** Connect the system to Databricks so the 5th health indicator turns green and all downstream features (routing, catalog browsing, benchmarking) are unblocked. Admin authentication: create `admin-credentials` K8s Secret, add `POST /api/auth/login` endpoint with Bearer token validation middleware on protected routes. Databricks credentials API: implement `POST /api/settings/databricks` (save PAT or service principal credentials to `databricks-credentials` K8s Secret, validate with `w.current_user.me()`, initialize `WorkspaceClient`) and `GET /api/settings/databricks` (return connection status, never return credentials). RBAC: create ServiceAccount + Role + RoleBinding so routing-service can create/update Secrets in its namespace. Settings modal in web-ui: "Settings" link next to health indicators opens a modal with Databricks workspace URL + PAT fields, validation feedback, and SQL Warehouse selector dropdown after successful connection. Update `/health/backends` to check Databricks connectivity — Databricks dot transitions from grey "Not Configured" → green "Connected" or red "Error". SQL Warehouse selection: `GET /api/databricks/warehouses` lists available warehouses, `PUT /api/settings/warehouse` persists the selection. Rebuild and redeploy both routing-service and web-ui images. Deliverable: admin can log in, configure Databricks credentials via the UI, select a SQL Warehouse, and see all 5 health indicators functional.

---

## Pending Fixes

Small items that don't warrant their own phase but should be addressed. These are folded into the next active phase or handled as quick standalone tasks.

- [x] **PostgreSQL schema: add collections tables.** The Phase 2 schema has `query_logs`, `routing_decisions`, `cost_metrics`, `table_metadata_cache`. Missing: `collections` (id, name, routing_mode, created_at) and `collection_queries` (id, collection_id FK, sequence, sql_text). Add via migration.
- [x] **routing-service module status.** Currently says "Planning" but has been deployed since Phase 1 with `/health` and since Phase 2 with `/health/backends`. Update to reflect actual state.
- [x] **data-populator trigger reference.** Still says "triggerable from the web-ui Operations page" but the Operations section was replaced by the Collections/Benchmark panel. Update wording.
- [x] **Delete `docs/API_ENDPOINTS.md`.** Content consolidated into PROJECT.md. File can be removed.

---

## Design Principles

**Cloud-Agnostic Architecture**
- Use Kubernetes instead of cloud-specific managed services
- Abstract cloud-specific connectors behind interfaces
- Reproducible on any cloud or local infrastructure

**Modularity**
- Separate concerns: parsing, metadata retrieval, routing decision, execution
- Pluggable routing strategies (enable/disable features via configuration)
- Per-query routing mode: every query carries a `routing_mode` field (`duckdb`, `databricks`, or `smart`) that overrides any global default
- Smart Routing exposes tunable parameters (`routing_params`): `complexity_threshold` (float, default 5.0 — queries scoring above this go to Databricks), `max_table_size_bytes` (int, default 1GB — tables larger than this go to Databricks), `check_governance` (bool, default true — whether to check row-level security / column masking)

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

## Decisions

- **2025-02-13:** Using Task Master for task management with tags per module
- **2025-02-13:** Single `.taskmaster` at project root, not per-module projects
- **2025-02-13:** PROJECT.md consolidates all project knowledge (no separate architecture.md, modules/*.md for now)
- **2025-02-13:** Development workflow: update PROJECT.md → generate PRD → task-master parse-prd → verify tasks.json
- **2026-03-04:** Chose TPC-DS (SF=100) as the primary benchmark dataset — predefined 99-query set enables out-of-the-box benchmarking; DuckDB tpcds extension eliminates external data download
- **2026-03-04:** data-populator runs as a Kubernetes Job triggered from the web-ui Operations page, not as a standalone script
- **2026-03-04:** Web UI expanded to include System Health, Query Console, Live Logs, Observability Dashboard, Router Configuration, and Operations sections
- **2026-03-05:** Adopted correlation_id (UUID) as the traceability mechanism across all services — generated at routing-service entry, passed to all backends, stored in query_logs alongside user_id. Backends are stateless with respect to users and sessions.
- **2026-03-05:** IaC strategy: Terraform + Helm. Terraform owns cloud infrastructure and Helm releases; Helm owns in-cluster application resources. Single terraform apply deploys everything. Chosen over Terraform-only (poor fit for app deployment lifecycle) and Pulumi (less mature Databricks provider).
- **2026-03-05:** Databricks IaC scope: reuse existing workspace and Unity Catalog metastore rather than provisioning from scratch. Terraform manages resources inside the existing workspace (catalog, schemas, SQL Warehouse, service principal, permissions) but does not create or modify the workspace or metastore. External dependencies provided as explicit input variables.
- **2026-03-06:** Web UI communicates exclusively with the routing-service — it has no direct connections to PostgreSQL or DuckDB worker. Backend health and query results are always proxied through the routing-service API. This keeps the UI decoupled from backend topology changes.
- **2026-03-07:** Decided to migrate web-ui from Streamlit to Vite + React + TypeScript served by FastAPI static files. Streamlit's execution model (full page rerun on every interaction) creates friction for interactive pages like Query Console and Live Logs. React gives full control over rendering, state, and polling without blocking constraints. UI theme TBD.
- **2026-03-08:** Dev environment requires Node.js 20+ and npm in addition to existing prerequisites (Docker, Minikube, kubectl, Python 3.13+, uv). Node.js is only needed locally for React development — it is not present in the production container (multi-stage Docker build).
- **2026-03-08:** Simplified web-ui from React + Vite + TypeScript to vanilla HTML + jQuery served by FastAPI. React was over-engineered for a dashboard that currently shows 5 health indicators. The new approach eliminates the Node.js dependency, the multi-stage Docker build, and the entire frontend/ directory. Auto-refresh polling (the original reason for leaving Streamlit) is trivially handled by setInterval + fetch in plain JavaScript. jQuery chosen for DOM manipulation convenience. All UI sections live on a single page — no sidebar navigation, no client-side routing.
- **2026-03-08:** Dev environment no longer requires Node.js — removed as part of React-to-vanilla-HTML simplification. Prerequisites are now: Docker, Minikube, kubectl, Python 3.13+, uv.
- **2026-03-08:** Databricks credentials stored in K8s Secret (`databricks-credentials`), written via routing-service API when user configures connection in the UI. Chosen over PostgreSQL (avoid secrets in DB) and config files on PVC (less elegant, harder to manage). Routing-service ServiceAccount needs RBAC to create/update Secrets.
- **2026-03-08:** Routing mode is per-query, not global. Each query submission includes a `routing_mode` field: `duckdb` (force DuckDB), `databricks` (force Databricks), or `smart` (use routing algorithm). Benchmarks use the same mechanism — all 99 TPC-DS queries run with the same routing mode, and different modes can be compared by running the benchmark multiple times.
- **2026-03-09:** Single admin login for local development. Username/password in K8s Secret (`admin-credentials`). Web-UI shows login form; routing-service API requires Bearer token. No user management, no roles. Cloud deployment auth (Azure AD, identity passthrough, managed identities) documented as Future Consideration but not in scope — it is substantial infrastructure plumbing that doesn't contribute to the core routing algorithm.
- **2026-03-08:** UI is a convenience layer, not the primary interface. All functionality (query submission, routing, benchmarking, Databricks configuration, catalog browsing) is exposed via the routing-service REST API. External services can use the API directly without the web-ui.
- **2026-03-09:** Introduced "collections" as the unified concept for saving and organizing queries. A collection is a named, ordered list of SQL queries with a routing mode (duckdb/databricks/smart) stored at the collection level. There are no standalone saved queries — all saved queries belong to a collection. A single-query collection serves as a "favorite." TPC-DS is a pre-built collection. Collections replace the separate "benchmark-runner" and "favorites" concepts. Benchmarking is just running a collection. Collections stored in PostgreSQL.
- **2026-03-09:** Single-page UI layout. Everything on one page: top bar with health indicators + settings link, left panel for Unity Catalog browser, center for query editor + results, right panel for collections. No multi-page navigation, no sidebar routing. Settings is a modal dialog triggered by a link next to the health indicators.
- **2026-03-09:** Routing mode is a page-level toggle (DuckDB / Databricks / Smart Router), not per-query. Opening a collection sets the toggle to the collection’s saved mode; the user can change it freely. Running a query or collection uses whatever the toggle currently shows. Saving a collection captures the current toggle state.
