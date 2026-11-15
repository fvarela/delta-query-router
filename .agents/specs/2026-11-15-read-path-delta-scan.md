# Read path: DuckDB `delta_scan` with credentials vended by Unity Catalog

Status: approved

## Goal
Milestone 1, first of three specs. Give the project the code that reads `dqr.sf1` tables with DuckDB:
vend short-lived read-only credentials from Unity Catalog per table, expose each table to DuckDB as a view
over `delta_scan` authenticated with that SAS token, and run SQL against the views unchanged. The author
can try it from their own machine through the dev tool. Deploying it on Container Apps and deciding
whether path 1 passes is the next spec.

## Non-goals
- Path 2 (`deltalake` lists files, DuckDB `read_parquet`): built only if path 1 fails, and then only after the author picks the fallback (author's decision 2026-11-15).
- The worker HTTP API, Dockerfile, Container Apps, Bicep changes (spec 2 of milestone 1).
- The router, the credential cache, the Databricks service principal, Key Vault secrets (spec 3).
- Comparing results with Databricks, running TPC-DS queries, any SQL warehouse use (spec 2).
- Timing Delta log resolution apart from execution: with `delta_scan` the log is read inside the query; how to separate the two is a spec-2 question.
- Grants in code: the author grants `EXTERNAL USE SCHEMA` by hand.
- Any change to the Unity Catalog objects of the closed specs, or to the dev tool's existing actions.

## Context
- Source of truth: `docs/DESIGN.md` §3 "Data access" (router vends READ credentials, worker maps each table to a DuckDB view so SQL runs unchanged, path 1 = DuckDB `delta` extension with the vended SAS token, "unverified on Azure with a SAS token"), §7 (time credential vending and execution separately), §9 (`router/`, `worker/` packages; dev tool is a thin menu over plain functions).
- Already in place (verified on `main`): `uv run dqr` with `run(choose, ask, console, make_client)` in `src/dqr/cli/main.py`; `src/dqr/data/tpcds.py` (the 24 table names, `Step`); tables `dqr.sf1.<table>` registered, external, at `abfss://tpcds@<DQR_STORAGE_ACCOUNT>.dfs.core.windows.net/sf1/<table>/`, `store_sales` 2880404 rows; `duckdb`, `deltalake`, `pyarrow` are dependencies. No `src/dqr/router/` or `src/dqr/worker/` yet.
- Credential vending (verified, Azure Databricks docs via Context7): `POST /api/2.1/unity-catalog/temporary-table-credentials` with `table_id` and `operation: READ`. It requires the metastore flag `external_access_enabled` and the `EXTERNAL USE SCHEMA` privilege on the parent schema, grantable only by the catalog owner. On Azure the response carries `azure_user_delegation_sas.sas_token` (v1 `duckdb-worker/credential_vending.py`). `table_id` and `storage_location` come from `GET /api/2.1/unity-catalog/tables/{full_name}`. Not verified: the Python SDK method names for these calls.
- Verified 2026-11-15 by the author: the metastore has `external_access_enabled: true`, and the author granted `EXTERNAL USE SCHEMA` on `dqr.sf1` to their own user with `databricks grants update schema dqr.sf1 ... --json '{"changes":[{"principal":"<user>","add":["EXTERNAL_USE_SCHEMA"]}]}'` (no warehouse needed).
- DuckDB Azure auth (verified, DuckDB docs via Context7): `CREATE SECRET (TYPE azure, CONNECTION_STRING '...')`; a `SCOPE` (trailing slash) picks the secret per path prefix. Not verified: that `delta_scan` uses such a secret with a SAS-only connection string on `abfss://` paths. E9 finds out.
- TLS interception (verified, `v1:duckdb-worker/credential_vending.py`): v1 dropped `delta_scan` after "SSL CA cert errors due to TLS interception". The author's machine can run behind a TLS-intercepting corporate proxy; it is off now (author, 2026-11-15). E9 runs with it off.
- Invariants:
  - Public repo: no company identifiers; SAS tokens are secrets and are never printed, logged or written to disk.
  - Read-only: only `operation: READ` is requested; nothing writes to storage or Unity Catalog.
  - The dev tool's existing actions and guards stay as they are (AGENTS.md "Dev tool safety").
  - Unit tests never call Azure or Databricks.
- Easy to get wrong:
  - One SAS token per table, likely scoped to that table's folder: one DuckDB secret per table, scoped to its own location, not one secret for the container.
  - `abfss://` vs `az://` paths and the DFS vs Blob endpoint in the connection string; record what worked in Notes.
  - DuckDB errors may echo the connection string: replace every SAS token in a message before it is shown (E7).
  - `INSTALL delta` and `INSTALL azure` download DuckDB extensions once; the tests that load them need network the first time on a machine.

## Decisions

| Decision | Options | Chosen | Why |
|----------|---------|--------|-----|
| Milestone 1 split | 1, 2 or 3 specs | 3: this one (code + local try), then worker on Container Apps and the verdict, then router + service principal | Author's choice 2026-11-15: small checkable steps; only specs 2 and 3 cost money. |
| Read paths | Build both and compare; path 1 first | Path 1 only; path 2 only if path 1 fails, after the author chooses the fallback | Author's choice 2026-11-15. Changes DESIGN §3 ("compared in milestone 1"): needs a decision-log line. |
| Path 1 pass condition (applied in spec 2) | — | On Container Apps: `delta_scan` authenticates with the vended SAS token, row counts of the SF1 tables match Databricks, a handful of TPC-DS queries return identical results; DuckDB and extension versions recorded | Author's statement 2026-11-15. Recorded here so spec 2 starts from it. |
| `EXTERNAL USE SCHEMA` for the author | Manual `GRANT`; dev-tool action | Author runs it by hand once; if refused, asks a colleague | Author's choice 2026-11-15. |
| Code layout | — | `src/dqr/router/credentials.py`: `TableAccess` (full name, location, SAS token hidden from `repr`), `vend_read_credentials(client, full_names)`. `src/dqr/worker/reader.py`: `connect(accesses)` (one Azure secret per table scoped to its location, one view per table), `run_query(conn, sql)`, `redact(message, tokens)` | DESIGN §3: the router vends, the worker reads. Planner's call. |
| View names | Unqualified; three-part | Each view exists as `<catalog>.<schema>.<table>` (an in-memory attached DuckDB database named after the catalog) and the connection uses `<catalog>.<schema>`, so both `store_sales` and `dqr.sf1.store_sales` resolve | SQL runs unchanged whichever form it uses. Planner's call. |
| Local try | Dev-tool action; integration test | New dev-tool action "Read TPC-DS SF1 with DuckDB": vend for the 24 tables, `count(*)` through each view; no yes/no question | Free: no warehouse, only Unity Catalog API calls and storage reads. Planner's call. |
| Timings | — | Per table: vending ms and `count(*)` ms. Plus one line with the DuckDB version and the `delta` and `azure` extension versions | DESIGN §7; the author asked to record versions. Planner's call. |

## Examples
E1–E8 are unit tests: Databricks is a fake client, data is local Delta tables written with `deltalake` to a temporary folder. E9 is the author's manual run.

- E1 — vend credentials
  - Given: a fake client where the 24 `dqr.sf1` tables exist, each with a `table_id` and its `storage_location`, and vending returns an Azure SAS token per table
  - When: `vend_read_credentials` runs for the 24 full names
  - Then: it returns 24 `TableAccess` in the given order, each with that table's location and token; every vending call asked for `READ`; neither `repr` nor `str` of a `TableAccess` contains the token.
- E2 — missing table
  - Given: `dqr.sf1.item` does not exist (`tables.get` raises `NotFound`)
  - When: `vend_read_credentials` runs
  - Then: it raises an error naming `dqr.sf1.item`.
- E3 — vending refused
  - Given: vending for `dqr.sf1.customer` raises `PermissionDenied`
  - When: `vend_read_credentials` runs
  - Then: it raises an error naming `dqr.sf1.customer` and saying the caller needs `EXTERNAL USE SCHEMA` on `dqr.sf1`.
- E4 — no Azure token
  - Given: vending for a table returns no `azure_user_delegation_sas`
  - When: `vend_read_credentials` runs
  - Then: it raises an error naming that table.
- E5 — read local tables through views
  - Given: `store_sales` (3 rows) and `item` (2 rows) written as Delta to a temporary folder; `TableAccess` entries with those local paths and no token
  - When: `connect` builds the views and `run_query` runs `SELECT count(*) FROM store_sales`, the same with `dqr.sf1.store_sales`, and a join of `store_sales` with `item`
  - Then: the counts are 3 and 3, the join returns the expected rows, and each result reports its execution ms.
- E6 — one secret per table
  - Given: two `TableAccess` entries with `abfss://tpcds@acct.dfs.core.windows.net/sf1/store_sales/` and `.../sf1/item/` and dummy tokens
  - When: `connect` runs (no query)
  - Then: DuckDB lists two Azure secrets, each scoped to exactly one of the two locations; no secret is scoped to the container or the account.
- E7 — tokens never shown
  - Given: an error message that contains a token from the current `TableAccess` list
  - When: `redact` processes it
  - Then: every occurrence of the token is replaced by `***`, the rest of the message is unchanged; the menu shows read errors only after `redact`.
- E8 — menu
  - Given: faked prompts and fakes for vending and reading, as in `tests/test_cli.py`
  - When: the author picks "Read TPC-DS SF1 with DuckDB"
  - Then: it vends for the 24 `<catalog>.sf1.<table>` names in table-list order without a yes/no question, and shows 24 lines (table, rows, vending ms, count ms) and one versions line. Errors are one redacted message. The existing choices behave as before.
- E9 — real run (manual, plain result)
  - With the grant in place (done 2026-11-15), the author turns the TLS-intercepting proxy off and runs "Read TPC-DS SF1 with DuckDB". Expected: 24 lines without error, `store_sales` 2880404 rows. The result, the versions line and the connection-string form that worked go into Notes. If it fails with the proxy off, work stops and the author decides the next step (path 1 is not yet judged failed: that verdict is on Container Apps).

## Production checklist

- [ ] Config/secrets — no new setting (catalog from `DQR_CATALOG`, login from `DATABRICKS_CONFIG_PROFILE`); SAS tokens only in memory, hidden from `repr`, redacted from errors (E1, E7).
- [ ] Errors — missing table (E2), refused vending with the grant hint (E3), no Azure token (E4), DuckDB read errors redacted and shown as one message (E7, E8).
- [ ] Logging — N/A: an interactive tool; the printed report is the record.
- [ ] Tests — E1–E8 in the unit suite; E9 by hand.
- [ ] Deployment — N/A: nothing deployed; the author's grant and E9 run are manual.
- [ ] Rollback — revert the branch; the grant can be revoked with `REVOKE EXTERNAL USE SCHEMA ON SCHEMA dqr.sf1 FROM <user>`.
- [ ] Docs — `AGENTS.md`: the new menu action and that it needs the grant and the proxy off. DESIGN §3: path 1 first, path 2 only on failure after the author's choice; §13 a decision-log line dated 2026-11-15.

## Open questions
None.

## Tasks

Generated by the create-tasks skill. The user may reorder, split or remove tasks before work starts; the executor only ticks checkboxes.

- [x] T1: Vend read-only table credentials from Unity Catalog
  - Why: Every DuckDB read needs a short-lived SAS token per table, and DESIGN §3 puts vending in the router. The failures the author will actually hit (missing table, missing grant, non-Azure response) must name the table and, for the grant, say what to do. The token is a secret, so it must never appear when the object is printed.
  - Files: `src/dqr/router/__init__.py` and `src/dqr/router/credentials.py` (new: `TableAccess` with full name, location and token hidden from `repr`/`str`; `vend_read_credentials(client, full_names)` returning `TableAccess` in order, recording vending ms per table, requesting `READ` only), `tests/test_credentials.py` (new: a fake client mirroring `databricks-sdk` — `tables.get` raising `databricks.sdk.errors.NotFound` for a missing table, the vending call returning or raising `PermissionDenied` as scripted, recording calls).
  - Done when: the tests for E1, E2, E3 and E4 pass, and all earlier tests still pass.
  - Out of scope: caching or refreshing tokens; any call to a real workspace; `READ_WRITE`; the DuckDB side; the menu.

- [x] T2: DuckDB views over `delta_scan` with one secret per table
  - Why: The worker must run SQL unchanged against `dqr.sf1` tables, so each table becomes a view reachable by plain and full name. Each vended token only covers its own table, so each gets its own scoped DuckDB secret. DuckDB errors may echo a token, so a redaction helper is needed before anything is shown.
  - Files: `src/dqr/worker/__init__.py` and `src/dqr/worker/reader.py` (new: `connect(accesses)` — loads `delta` and `azure`, one Azure secret per entry with a token scoped to its location, an attached in-memory database named after the catalog with one view per table over `delta_scan`, the connection using `<catalog>.<schema>`; `run_query(conn, sql)` returning rows and execution ms; `redact(message, tokens)`), `tests/test_reader.py` (new; local Delta tables written with `deltalake` to a temporary folder).
  - Done when: the tests for E5, E6 and E7 (the `redact` part) pass, and all earlier tests still pass.
  - Out of scope: any read from Azure in tests; path 2 (`read_parquet`); timing Delta log resolution separately; the worker HTTP API.

- [x] T3: "Read TPC-DS SF1 with DuckDB" in the dev tool, and docs
  - Why: The author needs a free way to try path 1 against the real tables from their machine (E9) before spec 2 deploys it. The report must carry the timings and versions the thesis needs, and errors must be shown redacted. DESIGN §3 must reflect the author's decision that path 2 is built only if path 1 fails.
  - Files: `src/dqr/cli/main.py` (new choice, no yes/no question; vend for the 24 `<catalog>.sf1.<table>` names in table-list order, `count(*)` each through the views; report table, rows, vending ms, count ms, plus one line with the DuckDB version and the `delta` and `azure` extension versions; errors shown as one message after `redact`), `tests/test_cli.py`, `AGENTS.md` (the new action; it needs `EXTERNAL USE SCHEMA` on `dqr.sf1` for the user and the CLI command to grant it with `<user>` as placeholder; a TLS-intercepting proxy breaks DuckDB's Azure reads, so turn it off), `docs/DESIGN.md` (§3: path 1 first, path 2 only if path 1 fails and after the author chooses the fallback; §13 a decision-log line dated 2026-11-15).
  - Done when: the tests for E8 and the menu part of E7 pass, all earlier tests still pass, and AGENTS.md and DESIGN say what is listed under Files.
  - Out of scope: running the action for real (E9 is the author's); SF10 in the menu; Databricks comparisons; any warehouse use.

## Notes

- 2026-11-15, T2, before any edit. Checked with DuckDB 2.0.0 (`delta` 9dcfb65b99, `azure` 906e92458c; both install fine here):
  - Works: `ATTACH ':memory:' AS dqr`, `CREATE SCHEMA dqr.sf1`, a view over `delta_scan` of a local Delta folder, `USE dqr.sf1`; then `store_sales` and `dqr.sf1.store_sales` both resolve (E5 is feasible). `CREATE SECRET (TYPE azure, CONNECTION_STRING ..., SCOPE '<abfss path>/')` registers and shows the scope (E6 secrets are feasible).
  - Problem: `CREATE VIEW ... AS SELECT * FROM delta_scan('abfss://...')` is NOT lazy. DuckDB binds the query when the view is created, so it reads the Delta log right then. With the fake abfss locations of E6 it tries the network (it fell through to the Azure managed-identity endpoint and failed after about 13 s). So "`connect` runs (no query)" with fake abfss paths cannot succeed if `connect` also creates the views.
  - Consequence for E8/E9: on the real run the Delta log resolution (the part spec 1 says it will not time apart) happens inside `connect`, not in the `count(*)` ms. So "count ms" will be mostly data scan time, and the log read is in the connect time.
  - Options:
    1. Split: `register_secrets(conn, accesses)` (extensions, secrets, attached DB, schemas) and `create_views(conn, accesses)`; `connect(accesses)` calls both. E6 then calls `register_secrets` (or `connect` is not called with abfss paths). E5 still calls `connect`. Small change to E6's "When".
    2. Keep `connect` only, with a keyword `create_views: bool = True`; E6 calls `connect(..., create_views=False)`. Same effect, one function, a flag only tests use.
    3. Make views lazy some other way (a table macro per table). Not possible with the two-name requirement (`store_sales` and `dqr.sf1.store_sales` as plain relations) without more machinery.
  - Recommendation: option 1. It keeps `connect` as the one call the menu uses, and the split also gives T3 a place to time view creation (the Delta log read) separately if the author wants it later. Needs the author's OK because E6's "When" changes (the tests are a contract).
- 2026-11-15, T2: the author chose option 1. `reader.py` has `register_secrets(conn, accesses)`, `create_views(conn, accesses)` and `connect(accesses)` calling both. E6 calls `register_secrets`; its Then is unchanged. E5 and E8 use `connect`.
- 2026-11-15, T2 plan changes by the author: (1) `register_secrets` raises a clear error for an `abfss://` location with an empty token; only local paths get no secret. (2) The location string is used exactly as Unity Catalog returns it, for both the secret scope and the `delta_scan` path (no added trailing slash). (3) `redact` also masks URL-encoded forms of each token and the value of any `sig=` parameter, with a test case.
- 2026-11-15, E9 gap, found when the author asked whether E9 includes two HTTP-logging checks (the log is fetched per query; the SAS is used and there are no managed-identity calls): it does not. E9 as written only asks for 24 lines without error, `store_sales` rows, versions and the connection-string form. Adding the two checks changes E9, so it needs the author's go in Examples (the planner's file); until then T3 does not implement them. Verified: DuckDB 2.0.0 has logging settings (`enable_logging`, `enabled_log_types`, `logging_storage`, `redact_http_logs`, table `duckdb_logs`). Not verified: that `delta_scan` (delta-kernel, its own object-store client) goes through DuckDB's HTTP logger at all. If it does not, the two checks need another method (for example a proxy log). Also seen: with a fake abfss path and no valid token, DuckDB fell back to the managed-identity endpoint (169.254.169.254), so "no managed-identity calls" is observable at least as an error path.
- 2026-11-15, E9 first real run (the author, proxy off): `Error: Invalid Input Error: A invalid connection string has been provided.` Cause (verified in the `duckdb-azure` source and reproduced offline with a dummy token on DuckDB 2.0.0): for a fully qualified `abfss://<container>@<account>.dfs...` path the extension requires `AccountName=<account>` in the connection string and throws that message otherwise. Fix in `register_secrets`: the string is now `AccountName=<account>;BlobEndpoint=https://<account>.blob.core.windows.net;SharedAccessSignature=<token>`, with a regression test (`test_secret_connection_string_names_the_account`). After the fix and with a dummy token the check passes and the request reaches Azure (403 for the dummy token, as expected). Not verified: a real token. The author reruns E9. The connection-string form that worked is still to be recorded here after that run.

