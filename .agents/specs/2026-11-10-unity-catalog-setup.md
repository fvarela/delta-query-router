# Unity Catalog setup: dev tool skeleton, credential, location, catalog, schemas

Status: approved

## Goal
A small interactive dev tool (`uv run dqr`) with two actions. "Set up Unity Catalog" creates the objects that let
Databricks read our `tpcds` container: a storage credential, an external location, the catalog `dqr` and the
schemas `sf1` and `sf10`. "Tear down Unity Catalog" removes exactly what setup created. Spec 3 (`tpcds-sf1`)
then registers tables in these schemas.

## Non-goals
- External tables and TPC-DS data (spec 3, `tpcds-sf1`).
- External volumes, mounts.
- Grants to anyone else, including the future Databricks service principal (milestone 1).
- The Databricks service principal itself; the dev tool runs as the author.
- Any Azure resource change: Bicep is done (closed spec `infra-bicep`).
- Reusing an existing storage credential; if creating ours is refused, that is decided in a follow-up (see Context).
- A non-interactive command line with subcommands; the plain functions are the script interface.

## Context
- Source of truth: `docs/DESIGN.md` §2 (rules: money, resources only through `infra/` or the dev tool, company identifiers), §4 (Unity Catalog objects are created by the dev tool with the Databricks SDK), §5, §9 (`cli/` is the dev tool with rich + questionary; `data/` holds Unity Catalog registration; "the dev tool is a thin menu over plain functions").
- Repo today: `src/dqr/__init__.py` only; no runtime dependencies; `tests/test_infra.py` holds the E8 leak guard (`ENV_VARIABLES`, `_needles`, `_read_env`). `.env.example` lists `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `UC_IDENTITY_RESOURCE_ID`.
- Deployed (closed spec `infra-bicep`): resource group `rg-dqr` with our ADLS Gen2 account and container `tpcds`. The dev workspace's existing Access Connector's user-assigned identity has Storage Blob Data Contributor on `tpcds`. Our storage account name is not secret (Bicep creates it): `az storage account list --subscription "$AZURE_SUBSCRIPTION_ID" -g rg-dqr --query "[0].name" -o tsv`.
- How Unity Catalog reaches storage: storage credential (names the connector and the identity) → external location (an `abfss://` URL plus one credential) → tables at paths under that URL (spec 3).
- Author's rights (verified 2026-11-10 with read-only `databricks grants get-effective` on the author's profile): through a group, `CREATE_CATALOG`, `CREATE_STORAGE_CREDENTIAL` and `CREATE_EXTERNAL_LOCATION` on the metastore. Not verified: whether Databricks also requires Azure rights on the connector to create a credential on it; the first real run shows it.
- The metastore has a default storage root (verified), so a catalog can be created without a managed location. That root is company storage: nothing in this project may create managed tables or managed volumes.
- SDK facts (Databricks SDK docs via Context7): `w.storage_credentials.create(name, azure_managed_identity=AzureManagedIdentityRequest(access_connector_id, managed_identity_id), comment)`; `w.external_locations.create(name, url, credential_name, comment)` validates access unless `skip_validation`; `catalogs.create(name, comment)`, `schemas.create(name, catalog_name, comment)`; each API has `get` and `delete`. A missing object raises `databricks.sdk.errors.NotFound` (or a subclass such as `ResourceDoesNotExist`).
- Invariants:
  - Public repo: nothing committed may identify the company (AGENTS.md). The workspace URL lives in the author's `~/.databrickscfg`; the connector id, identity id and any existing catalog name live in `.env`. Names our code creates (`dqr-storage`, `dqr-tpcds`, `dqr`, `sf1`, `sf10`) are fine.
  - The dev tool never changes or deletes an object it did not create (marker rule, see Decisions).
  - Unit tests never call Databricks; they use a fake client.
- Easy to get wrong:
  - Teardown order is the reverse of setup: schemas, catalog, external location, credential. A credential or location still in use cannot be deleted.
  - Dropping a schema that holds tables needs `force=True`; for external tables this drops only metadata, never the files. The catalog is deleted without force, so a catalog that holds anyone else's schema is never dropped.
  - Never print or log `.env` values in errors; name the variable.

## Decisions

| Decision | Options | Chosen | Why |
|----------|---------|--------|-----|
| Storage credential | Create our own; reuse the existing dev one | Our own, `dqr-storage`, on the existing connector and its user-assigned identity | Author's choice 2026-11-10: we own it, teardown can remove it, its name can be public. |
| Catalog | New catalog `dqr`; schemas in an existing catalog | New catalog, name from setting `DQR_CATALOG` (default `dqr`) | Author's choice 2026-11-10. If creating it is refused, the author sets `DQR_CATALOG` to an existing catalog in `.env`; no code change. |
| Ownership marker | Track created objects in a local file; a comment on each object | Every object setup creates gets the comment `Managed by the delta-router dev tool (dqr)`; teardown deletes only objects with exactly that comment | Works across machines and after a lost file; protects an existing catalog used as fallback. Planner's call. |
| Existing object with our name | Adopt it; stop | Stop before creating anything, naming the object; exception: an existing catalog is used as is (only schemas are added) | Never take over someone else's object; the catalog exception is the agreed fallback. Planner's call. |
| Settings | `config/` file; environment variables | Environment variables, loaded by the author from `.env`: `UC_ACCESS_CONNECTOR_ID` (new), `UC_IDENTITY_RESOURCE_ID`, `DQR_STORAGE_ACCOUNT` (new), `DQR_CATALOG` (new, optional), `DATABRICKS_CONFIG_PROFILE` (new, read by the SDK itself) | The values are company identifiers or per-machine; DESIGN §9 allows environment variables. Planner's call. |
| Databricks login | Service principal; author's CLI profile | The author's CLI profile, through `DATABRICKS_CONFIG_PROFILE` | The service principal does not exist yet (milestone 1); the profile already works. Planner's call. |
| Code layout | All in `cli/`; functions in `data/`, menu in `cli/` | `src/dqr/data/unity_catalog.py` (settings, `setup`, `teardown`, plain functions taking a client); `src/dqr/cli/` (menu only); project script `dqr` | DESIGN §9: thin menu over plain functions. |
| Teardown confirmation | Yes/no prompt; type the catalog name | `teardown` takes the typed confirmation and refuses unless it equals the catalog name | A yes/no is too easy to press by mistake; testable at function level. Planner's call. |
| New dependencies | Runtime; a separate group | `databricks-sdk`, `rich`, `questionary` as project dependencies | Simplest now; image slimming is decided in milestone 1 (DESIGN §9). Planner's call. |
| Real-workspace check | Integration test; manual run | Manual: the author runs setup once in the dev workspace | An integration test would create and drop the real `dqr` catalog the project uses. Planner's call. |

## Examples
E1–E7 run against a fake client in unit tests. E8 extends the existing leak guard. E9 is a manual check by the author.

- E1 — setup on an empty metastore
  - Given: all settings set, `DQR_CATALOG` unset, and none of the five objects exists
  - When: `setup` runs
  - Then: it creates, in this order: storage credential `dqr-storage` with `access_connector_id` = `UC_ACCESS_CONNECTOR_ID` and `managed_identity_id` = `UC_IDENTITY_RESOURCE_ID`; external location `dqr-tpcds` with URL `abfss://tpcds@<DQR_STORAGE_ACCOUNT>.dfs.core.windows.net/` and credential `dqr-storage`; catalog `dqr`; schemas `sf1` and `sf10` in `dqr`. Each gets the marker comment. The returned report has five lines, each "created" with the object type and name.
- E2 — setup is idempotent
  - Given: the state after E1
  - When: `setup` runs again
  - Then: no create call is made, and the report shows the five objects as "exists".
- E3 — a name clash stops setup
  - Given: a storage credential, external location or schema with our name exists without the marker comment (one case each)
  - When: `setup` runs
  - Then: it raises an error naming that object's type and name, and no create call is made at all (all checks run before the first create).
- E4 — existing catalog as fallback
  - Given: `DQR_CATALOG` names a catalog that exists without the marker, and the other four objects do not exist
  - When: `setup` runs
  - Then: it creates the credential, the location and both schemas in that catalog, does not create or change the catalog, and reports it as "exists, not managed".
- E5 — teardown removes only what setup created
  - Given: the state after E1, plus (separately) the state after E4
  - When: `teardown` runs with the confirmation equal to the catalog name
  - Then: it deletes, in this order: schemas `sf10` and `sf1` with `force=True`, the catalog without force (only if it has the marker), the external location, the credential. After E4 the catalog is kept and reported "kept, not managed". Objects that do not exist are reported "absent" and cause no error.
- E6 — teardown needs the typed confirmation
  - Given: the state after E1
  - When: `teardown` runs with a confirmation that differs from the catalog name (including empty)
  - Then: it raises an error and makes no delete call.
- E7 — missing settings
  - Given: one or more of `UC_ACCESS_CONNECTOR_ID`, `UC_IDENTITY_RESOURCE_ID`, `DQR_STORAGE_ACCOUNT` is unset or empty
  - When: settings are loaded
  - Then: an error lists the missing variable names, never any value, before any Databricks call.
- E8 — leak guard covers the new identifiers
  - Given: `.env` sets `UC_ACCESS_CONNECTOR_ID`, and optionally `DQR_CATALOG`
  - When: the E8 tests in `tests/test_infra.py` run
  - Then: no tracked or new file contains the connector's resource group or name taken from `UC_ACCESS_CONNECTOR_ID`, nor the `DQR_CATALOG` value unless it is `dqr`. `.env.example` lists every variable of the Settings decision with an empty value.
- E9 — real run (manual, plain result)
  - The author runs `uv run dqr` → "Set up Unity Catalog" in the dev workspace; the five objects exist, and the external location was created with validation on (so Databricks could reach `tpcds`).

## Production checklist

- [ ] Config/secrets — settings from environment variables loaded from `.env`; names in `.env.example`; no secret, no workspace URL in the repo.
- [ ] Errors — clear messages for missing settings (E7), name clashes (E3), wrong confirmation (E6); SDK errors (for example permission denied) are shown with the object being created.
- [ ] Logging — N/A: an interactive tool; the report printed with rich is the record.
- [ ] Tests — E1–E8 in the normal unit suite with a fake client; E9 by hand.
- [ ] Deployment — the author runs setup once (E9); no cost (metadata only).
- [ ] Rollback — the dev tool's teardown; nothing outside the five objects is touched.
- [ ] Docs — `AGENTS.md`: how to run the dev tool (`set -a; source .env; set +a`, then `uv run dqr`) and how to fill `DQR_STORAGE_ACCOUNT`; DESIGN §4: the credential is ours (`dqr-storage`) on the existing connector, catalog `dqr`.

## Open questions
None.

## Tasks

Generated by the create-tasks skill. The user may reorder, split or remove tasks before work starts; the executor only ticks checkboxes.

- [x] T1: Settings and `setup` with a fake client
  - Why: Setup is the core of this spec and must be safe before it ever touches the real workspace: idempotent, never adopting someone else's object, and failing early on missing settings. Building it as plain functions over an injected client lets the unit tests use a fake (E1–E4, E7).
  - Files: `pyproject.toml` and `uv.lock` (`uv add databricks-sdk`), `src/dqr/data/__init__.py` (new subpackage), `src/dqr/data/unity_catalog.py` (settings loaded from environment variables, marker constant, `setup(client, settings)` returning the report), `tests/test_unity_catalog.py` (a small fake client exposing `storage_credentials`, `external_locations`, `catalogs`, `schemas` with `get`/`create`/`delete`, raising `databricks.sdk.errors.NotFound` for missing objects, and recording calls).
  - Done when: the tests for E1, E2, E3, E4 and E7 pass.
  - Out of scope: teardown, the menu, `rich`/`questionary`, `.env.example`, docs; any call to a real workspace; grants; tables.

- [x] T2: `teardown` with marker check and typed confirmation
  - Why: Teardown is the rollback of this spec, and the riskiest function: it deletes things in a shared company metastore. It must delete only objects carrying our marker, in reverse order, and only after the typed confirmation (E5, E6).
  - Files: `src/dqr/data/unity_catalog.py` (`teardown(client, settings, confirmation)` returning the report), `tests/test_unity_catalog.py`.
  - Done when: the tests for E5 and E6 pass, and E1–E4, E7 still pass.
  - Out of scope: the menu; force-deleting the catalog, external location or credential; any call to a real workspace.

- [ ] T3: The `dqr` dev tool menu, settings template, leak guard and docs
  - Why: The author needs one command to run setup and teardown, the new `.env` variables must be documented without values, and the leak guard must cover the new company identifiers (E8). The decisions of this spec change DESIGN §4 and AGENTS.md.
  - Files: `pyproject.toml` and `uv.lock` (`uv add rich questionary`; project script `dqr = "dqr.cli.main:main"`), `src/dqr/cli/__init__.py`, `src/dqr/cli/main.py` (menu: set up, tear down (asks for the catalog name), quit; builds `WorkspaceClient()` so `DATABRICKS_CONFIG_PROFILE` applies; prints the report as a rich table; shows setting and SDK errors as one message, no traceback), a unit test of the menu dispatch with faked prompts (in `tests/test_unity_catalog.py` or a new `tests/test_cli.py`), `.env.example` (add `UC_ACCESS_CONNECTOR_ID=`, `DQR_STORAGE_ACCOUNT=`, `DQR_CATALOG=`, `DATABRICKS_CONFIG_PROFILE=`, one comment line each, no values), `tests/test_infra.py` (E8: needles for `UC_ACCESS_CONNECTOR_ID` (its resource group and name) and for `DQR_CATALOG` unless `dqr`; `.env.example` check covers all names), `AGENTS.md` (run the dev tool: `set -a; source .env; set +a`, then `uv run dqr`; fill `DQR_STORAGE_ACCOUNT` with the read-only `az storage account list` command from Context), `docs/DESIGN.md` §4 (the storage credential is ours, `dqr-storage`, on the existing connector; catalog `dqr`; schemas `sf1`, `sf10`; no names of pre-existing objects).
  - Done when: the E8 tests pass with the author's `.env` filled in (so the new value checks run), a unit test shows each menu choice calls the matching function, and DESIGN and AGENTS.md say what is listed under Files.
  - Out of scope: running the tool against the real workspace (E9 is the author's); subcommands; tables; grants.

## Notes
- T1: checked the real `databricks-sdk` 0.164.0 signatures before writing the fake (2026-11-10). `schemas.get` and `schemas.delete` take `full_name` ("catalog.schema"); `storage_credentials`, `external_locations` and `catalogs` take `name`. `delete` has `force`. `databricks.sdk.errors.NotFound` exists. The fake in `tests/test_unity_catalog.py` mirrors these, including `delete` for T2.
- T1: the report type is `Step(kind, name, status)`; schemas are reported with their full name (`dqr.sf1`); statuses are `created`, `exists`, `exists, not managed`. T2's teardown report should reuse `Step`.
- T1: the red run used a stub module whose functions raise `NotImplementedError`, so the tests failed on missing behaviour, not on a missing import.
- T1: not specified, decided while building: an existing credential or external location that carries our marker counts as "exists" even if its URL or identity differ from the settings. Setup does not compare or repair them.
- T1: when the catalog does not exist yet, setup skips the schema lookups (no catalog means no schema), so it does not depend on how the real API reports a schema in a missing catalog.
- T2: `teardown` reports `deleted`, `absent` or `kept, not managed` (an object without our marker is never deleted; the wording is the executor's). The typed confirmation must equal the catalog name exactly (case and spaces count); a mismatch raises `TeardownError` before any lookup or delete. The setup helper `_Item.create` was renamed `act`, since teardown reuses it.
- T2: the fake client's `delete` now raises `NotFound` for a missing object, like the real SDK, so a delete on an absent object fails a test instead of passing silently.
- T2: not covered by the fake (it does not model non-empty catalogs): if our catalog holds a schema that is not ours, the real `catalogs.delete` without force is expected to refuse. Teardown then stops with the SDK error after the schemas are already deleted; the location and credential stay. Rerunning is safe. T3's menu must show that error as one message.
