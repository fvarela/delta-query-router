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
**Purpose:** Interactive web interface for query submission and observability  
**Status:** Not started  
**Requirements:**
- Query submission form
- Real-time routing decision visualization
- Cost savings metrics dashboard
- Query history and filtering
- Routing configuration controls

**Tech Stack:** Streamlit, Python

### benchmark-runner (Evaluation)
**Purpose:** Execute benchmark queries and measure routing performance  
**Status:** Not started  
**Requirements:**
- Load benchmark query sets (TPC-H, TPC-DS, or custom)
- Execute queries sequentially with routing
- Measure and log latency, cost, accuracy
- Generate comparison reports (router vs all-Databricks baseline)
- Support A/B testing of routing strategies

**Tech Stack:** Python, databricks-sdk

### data-populator (Test Data)
**Purpose:** Populate Delta Lake tables from public datasets for testing  
**Status:** Not started  
**Requirements:**
- Download public datasets (e.g., NYC Taxi, IMDB)
- Convert to Delta Lake format using DuckDB
- Upload to Databricks Unity Catalog
- Create tables with varying sizes (small, medium, large)
- Apply sample governance rules for testing

**Tech Stack:** Python, DuckDB, deltalake-python, databricks-sdk

### infrastructure (IaC)
**Purpose:** Terraform configuration for all cloud resources  
**Status:** Not started  
**Requirements:**
- Kubernetes cluster (AKS/EKS/GKE)
- Databricks workspace and Unity Catalog
- SQL Warehouse configuration
- PostgreSQL StatefulSet
- Networking and ingress
- Spot node pools for DuckDB workers

**Tech Stack:** Terraform, Helm charts

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
