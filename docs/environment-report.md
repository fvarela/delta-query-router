# Environment report

- Generated: 2026-10-17 17:20 CEST (Europe/Paris)
- Branch: `main`
- HEAD: `7cc4b896436dc8b9beb32a0d0bc3bfa314f96e6c` ("latest changes", 2026-10-17 16:52 +0200)

Overall: the live environment was not reachable. minikube is stopped, the only other context is an unrelated AKS cluster that does not resolve, and there is no Terraform state. Nothing was started or modified. Sections 3, 4, 6, 7 and 8 are Blocked. `docs/data/` is empty (no CSVs were exported).

## 1. Git — Status: Done
Method: `git fetch --all` (no prune), `git for-each-ref`, `git rev-list --left-right --count main...<ref>`, `git status --ignored`, `git stash list`. All measured.

Current branch `main`, tracking `origin/main`, in sync (0/0). Working tree: no staged, unstaged or untracked-unignored changes at the time of the check. No stashes.

"Behind main" = commits on main not in the ref; "ahead of main" = commits on the ref not in main. Every ref is 0 ahead of main, so every branch is fully merged into main.

| Ref | Last commit (hash, date, subject) | vs upstream | behind main / ahead of main |
|---|---|---|---|
| main | 7cc4b89, 2026-10-17, latest changes | in sync with origin/main | 0 / 0 |
| feature/phase15-ui-redesign | c0602b2, 2026-04-10, docs: mark Phase 15 Stage B complete (590 tests passing) | **ahead 8 of origin/feature/phase15-ui-redesign** | 50 / 0 |
| feature/phase2 | 089c131, 2026-03-06, docs: update README for 4-service architecture | in sync | 174 / 0 |
| feature/phase5 | 92f6dc4, 2026-03-09, feat: complete Phase 5 | no upstream (local only) | 160 / 0 |
| feature/phase6 | e0c0c79, 2026-03-10, feat: add auth/settings proxy routes... | in sync | 155 / 0 |
| feature/phase7 | 35e7292, 2026-03-22, fix: restore 6 broken mock API functions | no upstream (local only) | 142 / 0 |
| feature/phase8 | 5ecd590, 2026-03-27, fix: extract IfThenRulesModal... | in sync | 116 / 0 |
| origin/feature/phase11 | 7a0bf56, 2026-04-02, docs: add deployment walkthrough and tfvars example | remote only | 76 / 0 |
| origin/feature/phase12 | 4002c0d, 2026-04-04, feat: complete phase 12 | remote only | 75 / 0 |
| origin/feature/phase15-ui-redesign | e05182a, 2026-04-09, feat: rewrite TPC-DS wizard (round 34) | remote only | 58 / 0 |
| origin/feature/phase17-engine-lifecycle-scoring-logs | cb859f3, 2026-04-11, feat: Phase 17 | remote only | 43 / 0 |
| origin/feature/phase18-cleanup-validation | 1c7e326, 2026-04-14, feat: DuckDB warmup runs real query through credential vending path | remote only | 23 / 0 |
| origin/feature/phase2, phase6, phase8 | same hashes as local branches | | |
| origin/main | 7cc4b89 | | 0 / 0 |

Unpushed work: only `feature/phase15-ui-redesign` (8 commits), plus local-only branches phase5 and phase7 (no upstream, but their commits are contained in main).
Ignored files present are listed in section 9.

## 2. Deployment — Status: Partial (nothing is live; Terraform state absent)
Method: `kubectl config get-contexts`, `minikube status`, `kubectl --context <c> get nodes`, `find infrastructure -name '*.tfstate*'`. Measured.

- Contexts: `minikube` (current) and `aks-mhs-airflow` (cluster `rg-mhs-airflow`, westus2 per its API hostname in kubeconfig).
- `minikube status` fails: `docker` is not available in this WSL distro ("could not be found... activate WSL integration"), so the minikube container state cannot be read. `kubectl --context minikube get nodes`: connection refused on 127.0.0.1:60311. So minikube is not running (or Docker Desktop is off). Not started, per instructions.
- `aks-mhs-airflow`: DNS lookup fails ("no such host"). This context is named for an Airflow project and is not shown to be related to delta-router; nothing in the repo refers to it. Unreachable either way.
- **Live deployment: nothing.** Neither minikube nor AKS was reachable. `kubectl get all`, PVCs, jobs, configmaps, ingresses and secret names: Blocked (no reachable cluster).
- Terraform (`infrastructure/terraform/`): no `*.tfstate*` file anywhere under `infrastructure/`, so there is no state to list. No Azure resources are recorded locally. The `.tf` files declare an RG, VNet, AKS, ACR and role assignment, NGINX and delta-router helm releases (inferred from AGENTS.md; the `.tf` files were not read). Task 59 (the actual Azure deployment) is documented as deferred, which fits.

**Restart side effects** (read from `routing-service/main.py` startup handlers and the modules they call; code-verified, not run). Starting the routing-service pod does the following:
- `init_database`: `db.init_db()`, then `benchmarks_api.recover_orphaned_runs()` deletes every `benchmark_runs` row with status `running`, `warming_up` or `pending` (cascades to `benchmark_results` and warmups via `ON DELETE CASCADE`). Then `query_features.backfill_all()` inserts missing `query_features` rows.
- `start_log_cleaner`: hourly background purge of old `query_logs` and related `routing_decisions`. Retention comes from the `log_settings` table (code default 30 days, 1024 MB).
- `cleanup_ephemeral_warehouses`: only if Databricks credentials were loaded. Deletes leftover `delta-router-ephemeral-*` warehouses that carry the management tag.
- Also: `engine_state` polling every 30 s and `idle_timer` start for on-demand DuckDB engines (not in the list given to me). `load_databricks_credentials` only reads `DATABRICKS_HOST`/`DATABRICKS_TOKEN` from the environment, which the deployments fill from the `databricks-credentials` Secret.

## 3. Postgres data — Status: Blocked
Blocked by decision: environment not started on 2026-10-17. No CSVs, no row counts. Needs: a running minikube with Postgres reachable (`postgresql-0`).

## 4. Startup times — Status: Blocked
Blocked by decision: environment not started on 2026-10-17. Needs: a running minikube with Postgres reachable (`engine_cold_starts`, `benchmark_engine_warmups`). Meaning, from PROJECT.md (documented, not measured): `engine_cold_starts` holds the routing-relevant latest cold start per engine (0 ms for DuckDB); `benchmark_engine_warmups` holds the raw warmup time recorded during benchmarks.

## 5. DuckDB overhead — Status: Partial
Method: read the code and notes only; no pod logs (cluster down), no DB.
- Worker code does log it (measured by reading `duckdb-worker/main.py`): `main.py:237-257` times credential vending with `perf_counter` and logs `"Credential vending: resolved in %.0fms (%d files total)"`, and on failure `"Credential vending failed after %.0fms"`. This is **per query, for all tables together**. `credential_vending.py` logs steps (lines 159, 167, 317, 358) but no per-table timings and no separate Delta-log timing.
- Not stored in Postgres: no column for it in `routing-service/db/schema.sql` (grep for vend/resolve found nothing). PROJECT.md line 329/344 says `credential_vending_ms` was deliberately not collected.
- `main.py:283` returns `execution_time_ms` that covers the whole request including vending (`start` is set before vending, line 231), so it is not separable in recorded results.
- Notes in repo: PROJECT.md line 812 states estimates "200-800 ms/table + 2-15 s Delta log per table" and "~2-6 s" for warmup. These are estimates written in notes, and I could not find the measurements behind them. No per-scale-factor data exists in the repo.
- Pod logs (the only place the per-query figure survives) could not be read: Blocked. Count/min/median/max: not available.

## 6. Unity Catalog `delta_router_tpcds` — Status: Blocked
Blocked by decision: Databricks not accessed on 2026-10-17. Needs: a valid PAT for the project workspace (the project workspace has not been confirmed). A token in `.env` was rejected as invalid.

## 7. Databricks — Status: Blocked
Blocked by decision: Databricks not accessed on 2026-10-17. Needs: a valid PAT for the project workspace (not yet confirmed). Workspace region: not determined.

## 8. Known failures — Status: Blocked
Blocked by decision: environment not started on 2026-10-17. Needs: a running minikube with Postgres reachable (`benchmark_results`).

## 9. Uncommitted notes — Status: Done
Method: `git status --ignored`, `ls -l`, first heading/line of each file. Location is working tree (ignored by `.gitignore`) unless stated. Branches: no file exists only on another branch (`git diff --stat main...<branch>` is empty for phase5/7, and all refs are 0 ahead of main). No stashes. `PROJECT.md` is tracked on main, not untracked.

| Path | Modified | Summary |
|---|---|---|
| AGENTS.md | 2026-06-07 | Project instructions and context notes (ignored, not on main) |
| THESIS.md | 2026-04-21 | Working thesis draft: Delta Router, query routing for Unity Catalog |
| .agents/docs/FEEDBACK.md | 2026-05-07 | User feedback on a smart-routing run with DuckDB Small and Databricks 2X-Small |
| .agents/docs/INPUT.md | 2026-07-09 | Short user decision ("Option C, fix the root cause") about a CA cert issue |
| .agents/docs/RESEARCH-PROMPT-UI-TEST-AGENT.md | 2026-05-06 | Research prompt on a vision-capable UI test agent |
| .agents/docs/UI-TESTS.md | 2026-05-06 | UI integration test plan against the minikube web-ui URL |
| .agents/docs/duckdb-uc-issue.md | 2026-06-17 | Upstream status of duckdb/unity_catalog managed-Delta credential vending bug |
| .taskmaster/CLAUDE.md | 2026-02-14 | Task Master agent integration guide |
| .taskmaster/config.json, state.json | 2026-03-26, 2026-04-01 | Task Master config and state |
| .taskmaster/tasks/tasks.json (+ 67 `task_*.md`) | 2026-05-07 (json) | Task database and generated per-task markdown (phases 3-9) |
| .taskmaster/docs/ (21 files, phase1..phase22 PRDs) | 2026-02-15 to 2026-05-07 | Per-phase PRDs; newest phase22 (query-time cold start tracking) |
| .taskmaster/templates/ (2 files) | 2026-02-14 | Example PRD templates |
| full-snapshot.md, right-panel-snapshot.md, ui-snapshot-full.md, smart-routing.md | 2026-04-13 to 04-21 | Playwright accessibility-tree dumps of the web UI |
| query-tab.png, routing-single-engine*.png, routing-smart-routing-mode.png | 2026-04-06, 2026-05-05 | UI screenshots |
| .env | 2026-06-07 | Local env file (values not recorded here) |
| minikube-linux-amd64 | 2026-02-15 | 134 MB minikube binary |
| .playwright-mcp/, .test-screenshots/, .vscode/, .ruff_cache/ | n/a | tool caches/config |
