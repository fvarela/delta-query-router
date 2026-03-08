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

**Streamlit (Web UI)**
- Purpose: Interactive dashboard for query submission, routing configuration, and observability
- Rationale: Rapid development in pure Python; built-in charting and data visualization; live metrics updates; perfect for prototypes and demos

### Core Libraries

**sqlglot**
- Purpose: SQL parsing and abstract syntax tree (AST) analysis
- Rationale: Pure Python; mature and well-tested; supports multiple SQL dialects; extracts query structure for complexity scoring

**databricks-sdk**
- Purpose: Unity Catalog integration and SQL Warehouse API access
- Rationale: Official Python SDK; handles authentication and API versioning; provides table metadata and governance information

**deltalake-python**
- Purpose: Direct Delta Lake table access for DuckDB
- Rationale: Enables DuckDB to read Delta tables without Spark; bindings to Rust Delta library; efficient columnar reads

### Observability

**PostgreSQL-Based Metrics Store**
- Purpose: Centralized logging of all query executions, routing decisions, and cost calculations
- Rationale: Single source of truth for evaluation; enables complex analytical queries for dashboards; supports A/B testing between routing strategies

**Streamlit Dashboard**
- Purpose: Real-time visualization of cost savings, latency distributions, and routing accuracy
- Rationale: Provides interactive exploration during development; useful for demos

---

## Modules

### routing-service (Core Router)
**Purpose:** Core routing logic that analyzes queries and makes routing decisions  
**Status:** Planning  
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
**Purpose:** Interactive web interface for query submission, observability, and operational control  
**Status:** Basic scaffold deployed (Phase 1)  
**Pages / Sections:**

**System Health**
- Five service indicators: Web UI (always green — implicit), Routing Service, PostgreSQL, DuckDB Worker, Databricks
- Databricks shows grey 'Not Configured' state until Databricks integration is implemented
- Landing page — first thing visible on load
- Polls the routing-service `/health/backends` endpoint every 15 seconds; polling mechanism moves to native React (setInterval) after Phase 4 migration

**Query Console**
- SQL editor for submitting queries through the router
- Displays routing decision alongside results: engine chosen, complexity score, reason
- Shows query execution time and estimated cost
- Primary interactive feature and demo surface

**Live Query Logs**
- View routing decision history from PostgreSQL for any query ID
- Filter by engine, status, time range
- Future: real-time log streaming from DuckDB worker or Databricks

**Observability Dashboard**
- Cost savings over time (router vs all-Databricks baseline)
- Routing distribution: % of queries routed to DuckDB vs Databricks
- Latency percentiles by engine
- Primary demo and evaluation surface

**Router Configuration**
- Adjust routing thresholds (complexity score cutoff, data size limits)
- Enable/disable governance constraint checks
- Switch between routing strategies
- Lower priority — implement after core routing logic is stable

**Operations**
- Trigger TPC-DS data ingestion job (see data-populator module)
- Expose scale factor selection (SF=1 for local dev, SF=100 for cloud)
- Show ingestion job status by polling Kubernetes Job state
- Clear table metadata cache
- Reset routing statistics

**Tech Stack:** Vite, React, TypeScript, FastAPI, Python

### benchmark-runner (Evaluation)
**Purpose:** Execute TPC-DS benchmark queries and measure routing performance  
**Status:** Not started  
**Requirements:**
- Load the TPC-DS predefined query set (99 queries) from the standard query templates
- Execute queries sequentially through the router and record routing decisions
- Execute the same queries directly on Databricks SQL Warehouse to establish the baseline
- Measure and log latency, cost, and routing accuracy for every query
- Generate comparison reports: router vs all-Databricks baseline
- Support A/B testing of routing strategies by swapping routing configuration between runs
- Depends on data-populator having completed successfully before running

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
- Runs as a Kubernetes Job, triggerable from the web-ui Operations page
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

## Future Integrations

Potential integrations that would extend the platform's value but are not yet scheduled as phases.

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

---

## Design Principles

**Cloud-Agnostic Architecture**
- Use Kubernetes instead of cloud-specific managed services
- Abstract cloud-specific connectors behind interfaces
- Reproducible on any cloud or local infrastructure

**Modularity**
- Separate concerns: parsing, metadata retrieval, routing decision, execution
- Pluggable routing strategies (enable/disable features via configuration)
- Profile-based routing (different rules for different user personas)

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
