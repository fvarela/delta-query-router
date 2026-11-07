# Delta Query Router: design

What we build and why, in one place. Short on purpose: if it is not here, it is not in scope.
Task specs reference this file instead of repeating it. Changing a decision needs the author's agreement
and a line in the decision log at the end.

## 1. Purpose

A research prototype for a master's thesis (Mathematics and Computational Engineering), not a product.

A router sits between SQL consumers and Databricks. For each query it chooses between a Databricks SQL
serverless warehouse and a cheaper DuckDB engine reading the same external Delta tables. The thesis shows
whether this beats the strongest Databricks-only setup (serverless with a tuned auto-stop) on cost,
at acceptable latency. The contribution is the routing and stop policy; the infrastructure exists to
produce trustworthy measurements and one end-to-end demo.

**Non-goals:** web UI, user management, routing profiles, rule editors, Kubernetes, an SDK, production
hardening, multi-cloud.

## 2. Project rules

These hold for every task, whoever or whatever writes the code.

- **Scope:** build only what this file describes. If a task needs something not covered here, or
  contradicts a decision, stop and ask.
- **Money:** anything that creates Azure resources, starts or creates a Databricks warehouse, starts a
  Container App or runs a benchmark costs money and needs the author's explicit go. This includes Python
  code that calls the Azure or Databricks APIs, which command-level permission rules do not catch.
- **Resources:** Azure resources only through `infra/` (Bicep); Unity Catalog objects only through the
  dev tool.
- **Secrets:** never in the repo. `.env` is git-ignored; deployed secrets live in Key Vault.
- **Company identifiers:** the repo is public and is deployed to the author's company Azure tenant. Never
  commit tenant, subscription, principal or object ids, or names of pre-existing resources (managed
  identities, service principals, networks, resource groups, workspaces), groups or people. They live only
  in the git-ignored `.env`; `.env.example` lists the variable names. Names of resources our Bicep creates
  are fine.
- **Results:** never delete or overwrite files in `results/`; a new run writes a new file.
- **Tests:** pure logic (cost model, state machine, queues, simulator, features) is unit-tested with
  pytest. Tests that need Azure or Databricks are marked `integration` and skipped by default.
  No Spark and no Databricks Connect in this project.
- **Legacy code:** the old implementation is at git tag `v1`. Read files with `git show v1:<path>`
  (section 10 lists the useful ones). Never restore whole v1 files or directories.

## 3. Architecture

```
consumer ──SQL──▶ router (Container App, 1 replica)
                    │  in-memory state: warehouse state, stop clock, queues
                    ├──▶ Databricks SQL serverless warehouse (existing workspace)
                    └──▶ DuckDB worker (Container App, min replicas 0 or 1)
                                │
                                ▼ reads via Unity Catalog credential vending
                         ADLS Gen2 storage: external Delta tables (TPC-DS)
```

- **Router:** FastAPI service. Parses the query (sqlglot), reads state from memory, filters feasible
  engines, scores them, dispatches. Exactly one replica, because state lives in memory.
- **DuckDB worker:** FastAPI service, one Container App on the Consumption profile, 4 vCPU / 8 GiB,
  max replicas 1, internal ingress only. Min replicas is an experiment setting: 1 = always on (billed
  while idle, no startup delay), 0 = scale to zero (billed only while working, cold start after idle).
  The thesis compares the two modes; the simulator evaluates both from one set of measurements.
- **Communication:** plain HTTP inside the Container Apps environment; the router calls the worker by
  app name. No Dapr and no external queue: the queue lives in the router, because routing needs its
  state. Container Apps ends an HTTP request after 240 s, so the worker is submit-and-poll:
  `POST /queries` returns an id at once, `GET /queries/{id}` returns status and result.
- **Databricks:** the existing workspace and its Unity Catalog. Not managed by our IaC.
- **Storage:** our own ADLS Gen2 account holds the Delta files. Both engines read the same files.
- **Results:** Parquet files in `results/`, one file per run (proposed).

### Data access (proposed, settled in milestone 1)

The router holds the Databricks identity. It vends short-lived, read-only table credentials from Unity
Catalog (`POST /api/2.1/unity-catalog/temporary-table-credentials`, `"operation": "READ"`), caches them
until shortly before expiry, and sends them to the worker with the query. The worker holds no long-lived
secret and has no direct permission on the storage account.

Inside the worker, each table name is mapped to a DuckDB view, so the SQL runs unchanged (no regex
rewriting). Two candidate read paths, compared in milestone 1:

1. DuckDB `delta` extension (`delta_scan`) with the vended SAS token. Handles deletion vectors and file
   skipping. Unverified on Azure with a SAS token.
2. Fallback (v1 approach): `deltalake` lists the files, DuckDB reads them with `read_parquet`. Ignores
   deletion vectors and partition values, so it is only correct for tables written once and unpartitioned,
   which ours are.
   DuckDB's `unity_catalog` extension is not used: it requests READ_WRITE credentials (upstream
   duckdb/unity_catalog#64, open).

## 4. Azure resources (Bicep, `infra/`)

All in one resource group, in the Databricks workspace's region (westus2, confirmed 2026-11-03).

| Resource                                               | Purpose                                                                                     |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Log Analytics workspace                                | Logs for the Container Apps environment                                                     |
| Container Apps environment                             | Hosts router and workers                                                                    |
| Container registry (Basic)                             | Router and worker images                                                                    |
| Container Apps: `router`, `worker`                     | See section 3; deployed in milestone 1, with the worker image                               |
| User-assigned managed identity                         | Used by the apps: AcrPull, Key Vault secrets reader                                         |
| Key Vault                                              | Databricks service principal secret                                                         |
| Storage account, ADLS Gen2 (HNS on), container `tpcds` | External Delta tables                                                                       |
| Existing Databricks Access Connector (not created here) | Its user-assigned identity, which the existing storage credentials use, gets Storage Blob Data Contributor on the container |

Unity Catalog objects are created by the dev tool with the Databricks SDK, not Bicep: storage credential
(on the existing Access Connector), external location, catalog, schemas `sf1` and `sf10`, external tables.

The author's own user can get the same role on the container through the optional `dataWriterPrincipalId`
parameter, so the data code can write the Delta files from the author's machine.

**Databricks identity:** a Databricks service principal with OAuth machine-to-machine credentials; the
secret lives in Key Vault. Not a personal access token. (The Python SDK does not yet support managed
identity login; a managed-identity Entra token passed to the SDK is a later option.)

## 5. Data

- TPC-DS generated with DuckDB (`CALL dsdgen(sf=N)`), written as Delta with `deltalake` to the storage
  account, registered with `CREATE TABLE ... LOCATION 'abfss://...'`.
- Scale factors: SF1 first, then SF10. SF100 only if no crossover appears by SF10, on a subset of queries.
- Unpartitioned, written once, never updated. No deletion vectors.
- Queries: the 99 TPC-DS queries from `tpcds_queries()`; any query needing changes to run on Databricks
  gets a recorded, minimal edit. A query that fails on an engine is recorded as infeasible there.
- **Known bias:** TPC-DS queries are complex, while real workloads are dominated by small, repetitive
  queries (van Renen et al., "Why TPC Is Not Enough", VLDB 2024; their public Redset dataset). TPC-DS
  therefore favours Databricks, so savings measured with it are a conservative estimate. First iteration:
  TPC-DS only. If needed later, add templated simple and medium queries over the same tables (point
  lookups, filtered scans, single-table aggregations, top-N, small joins) and report results by the share
  of simple queries, with a Redset-derived mix as the realistic case.

## 6. Routing model

For query q and state s, choose the feasible engine minimising cost plus priced latency:

```
e*(q, s) = argmin over e in F(q) of  C(q, e, s) + λ · L(q, e, s)
L(q, e, s) = 1[e cold] · T_start(e) + W_e(s) + T_exec(q, e)
```

- **Cost in euros.** C is the marginal cost the query adds: extra billed uptime × rate. Prices are
  parameters in `config/prices.toml` with source and date, never constants in code.
- **λ** is euros per second of waiting, a parameter swept in the results.
- **Feasibility F(q):** DuckDB is excluded when a table has row filters or column masks, the SQL fails to
  parse for DuckDB, or predicted memory exceeds the worker.
- **T_start:** measured distributions per engine and mode; used only when the engine is cold.
- **W_e(s):** queue wait = predicted remaining work of queued and running queries / k.
- **T_exec:** predicted warm execution time from the model trained on benchmark results.

### State and stop control

- The router owns the warehouse stop decision and calls the stop API when its policy says so. The
  warehouse's own auto-stop is set long, as a safety net only.
- Because the router is the warehouse's only client and causes every start and stop, its in-memory state
  is exact. No status API call on the hot path; a slow background poll detects drift.
- Stop policies are online (ski-rental) policies, evaluated in the simulator.

### Queueing

- One bounded FIFO queue per DuckDB worker inside the router, concurrency k = 1 to start.
- Databricks queues internally; the router only counts its own in-flight queries there.

## 7. Measurement protocol

- Benchmarks run on **warm** engines only. Discard the first run; keep N repeats (start N = 3).
- Databricks: `use_cached_result = false`; warehouse max clusters = 1; sizes 2X-Small, X-Small, Small;
  warehouses created per run and deleted afterwards.
- DuckDB: time credential vending, Delta log resolution and execution separately.
- Startup measured separately and repeatedly: warehouse stop → start → first result; Container Apps
  scale-from-zero → first result; warehouse STOPPING duration; warehouse API latency.
- Every result row records: run id, git SHA, timestamp, engine and its config, scale factor, query id,
  repeat, status, error, timings in ms, row count.

## 8. Evaluation

A discrete-event simulator replays arrival traces (Poisson, office-hours bursts, idle nights) against the
measurements and integrates each engine's billed uptime. Policies compared:

- Databricks serverless only, auto-stop τ swept (the baseline gets its best τ)
- Databricks pro only, τ swept (checks the baseline claim)
- Databricks only with router-controlled stop (ablation: stop timing vs routing)
- Size-threshold rule
- Model-based router
- Oracle with hindsight (upper bound)
  The live prototype runs one real workload; its measured cost and latency are compared with the
  simulator's prediction for the same trace.

## 9. Code layout and conventions

```
src/dqr/
  router/   state machine, features, cost model, policies, HTTP API
  worker/   DuckDB worker HTTP API
  data/     TPC-DS generation, Delta writing, Unity Catalog registration
  bench/    benchmark runner, startup measurements
  sim/      simulator, workload traces
  cli/      interactive dev tool (rich + questionary)
infra/      Bicep: main.bicep + modules, parameter files
docker/     router and worker Dockerfiles
config/     prices.toml, settings
analysis/   notebooks that build every thesis figure from results/
results/    measurement files (Parquet, committed)
tests/
```

- **sim/:** replays a workload trace on a virtual clock using measured times instead of running queries;
  tracks engine on/off states, queues and billing per policy. Most thesis results come from it.
- **data/:** code that generates TPC-DS, writes the Delta tables to ADLS and registers them in Unity
  Catalog. The data itself lives in storage, never in the repo.
- **analysis/:** Jupyter notebooks that read `results/` and draw every thesis figure and table. Logic
  stays in `src/`; notebook outputs are stripped before commit (nbstripout).
- Python 3.12, uv, ruff, pytest. One `pyproject.toml`; the two images install only what they need.
- The dev tool is a thin menu over plain functions; everything it does can also run from a script.
- Configuration from `config/` and environment variables.
- Simplest code that works: small modules, plain functions, type hints.

## 10. Legacy code (tag `v1`)

| v1 path                                                  | Useful for                                                                 |
| -------------------------------------------------------- | -------------------------------------------------------------------------- |
| `duckdb-worker/credential_vending.py`                    | UC credential vending calls, Azure SAS handling, abfss → https             |
| `routing-service/ephemeral_warehouses.py`                | Creating and deleting tagged benchmark warehouses                          |
| `routing-service/cold_start_measure.py`                  | Measuring warehouse startup                                                |
| `routing-service/query_analyzer.py`, `query_features.py` | sqlglot feature extraction                                                 |
| `routing-service/tpcds_queries.py`                       | The 99 DuckDB TPC-DS queries with catalog and schema templated via sqlglot |
| `routing-service/tpcds_api.py`                           | v1 generation: DuckDB dsdgen inside a Databricks job, written with Spark   |

## 11. Milestones

Each milestone becomes one or more task specs.

| #   | Milestone                      | Produces                                                                                                                      |
| --- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| 0   | Scaffold                       | v1 code removed from the working tree (kept at tag `v1`); `src/dqr/` package and `tests/`; pyproject, pytest and ruff working |
| 0.5 | Infrastructure, dev tool, data | Bicep for the shared base of section 4 (no apps); dev tool; TPC-DS SF1 written and registered in Unity Catalog                                             |
| 1   | Read-path spike                | DuckDB on Container Apps reading the tables both ways of section 3; a choice; the `router` and `worker` apps are deployed here                                                  |
| 2   | Benchmark runner               | All queries × engines × scale factors, warm, N repeats, results per section 7                                                 |
| 3   | Startup and API measurements   | Distributions listed in section 7                                                                                             |
| 4   | Simulator and policies         | Section 8; can start early with made-up numbers                                                                               |
| 5   | Predictor                      | Features + latency models (linear, gradient boosting), cross-validated                                                        |
| 6   | Live prototype                 | Router + workers on Container Apps; one real workload compared with the simulator                                             |
| 7   | Write-up                       | Thesis figures built from `results/` by `analysis/`                                                                           |

## 12. Open items

- Worker read path (milestone 1).
- Where to generate SF10: locally or as a Container Apps job next to the storage.
- Container Apps scale-to-zero cooldown: a second timeout parameter, to measure and include in the model.
- Thesis deadline (decides the size of the live prototype).

## 13. Decision log

| Date       | Decision                                                                                                    |
| ---------- | ----------------------------------------------------------------------------------------------------------- |
| 2026-10-17 | Baseline: Databricks SQL serverless with tuned auto-stop; verified against pro in the simulator             |
| 2026-10-17 | Objective: minimise cost + λ · latency; cost in euros                                                       |
| 2026-10-17 | Benchmarks warm only; startup measured separately                                                           |
| 2026-10-17 | Engines: Databricks SQL + DuckDB (warm and scale-to-zero); Polars dropped                                   |
| 2026-10-17 | Old measurements not reused                                                                                 |
| 2026-10-17 | Router owns the warehouse stop decision; long auto-stop as safety net                                       |
| 2026-10-17 | Bounded FIFO queue per DuckDB worker in the router, k = 1                                                   |
| 2026-10-17 | Azure Container Apps for router and workers; no Kubernetes                                                  |
| 2026-10-19 | Spec-first rebuild; v1 code as reference only                                                               |
| 2026-10-19 | Bicep for Azure resources; interactive Python dev tool                                                      |
| 2026-10-19 | TPC-DS generated with DuckDB, written as Delta, registered as external tables                               |
| 2026-11-01 | One design file; agent behaviour and git workflow live in the author's OpenCode setup, not in the repo docs |
| 2026-11-01 | One worker app; min replicas (0 or 1) is an experiment setting                                              |
| 2026-11-01 | Plain HTTP by app name, submit-and-poll worker; no Dapr, no external queue                                  |
| 2026-11-01 | TPC-DS only in the first iteration; simple-query family added only if needed                                |
| 2026-11-01 | Section 9 directories are created by the first task that puts a file in them; no placeholders               |
| 2026-11-03 | Container Apps router and worker deployed in milestone 1 with the worker image; milestone 0.5 deploys the shared base |
| 2026-11-03 | Reuse the dev workspace's Access Connector; its user-assigned identity gets Storage Blob Data Contributor on our container |
