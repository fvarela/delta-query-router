# Infra: Bicep for the shared Azure base

Status: approved

## Goal
Describe in Bicep, under `infra/`, the Azure resources the next steps need: storage for the Delta tables,
access to it for the identity of the dev workspace's existing Access Connector (which Unity Catalog uses
to reach storage), and the shared base the Container Apps will run on later. The author deploys it with one command. The two apps (`router`, `worker`) are
added in milestone 1, once a worker image exists.

## Non-goals
- The Container Apps `router` and `worker` (milestone 1).
- Dockerfiles and images.
- Unity Catalog objects (storage credential, external location, catalog, schemas): next spec, `unity-catalog-setup`.
- The Databricks service principal, and putting its secret into Key Vault (that is a manual step, done later).
- Private networking (VNet, private endpoints), CI pipelines, multiple environments.
- Creating an Access Connector, or changing anything in the dev workspace's resource group.

## Context
- Source of truth: `docs/DESIGN.md` §2 (money, resources, secrets rules), §3, §4, §9 (`infra/` = `main.bicep` + modules + parameter files).
- Repo today: `src/dqr/__init__.py`, `tests/` (conftest, smoke, pytest config), `pyproject.toml` with no runtime deps. No `infra/` yet; the first task that writes a file there creates it.
- Tools verified present: `az` (`/usr/bin/az`). The standalone `bicep` CLI is not installed; `az bicep build` compiles offline once `az bicep install` has fetched the compiler.
- Invariants:
  - Nothing in this spec creates Azure resources by itself. Deploying is a separate command the author runs after an explicit go (DESIGN §2, money rule).
  - No secret values in the repo, in parameter files or in templates. Key Vault is created empty.
  - All resources in one resource group, in the Databricks workspace's region (DESIGN §4).
  - The dev workspace's resources are only read (`existing` in Bicep), never created or changed.
  - Public repo, company tenant: nothing committed may identify the company or its pre-existing resources. No tenant, subscription, principal or object ids, and no names of pre-existing resources (managed identities, service principals, networks, resource groups, workspaces), groups or people, in code, tests, parameter files, docs, specs or commit messages. These values live only in the git-ignored `.env`. Names of the resources our Bicep creates (resource group `rg-dqr`, prefix `dqr`, container `tpcds`) are fine (author, 2026-11-03).
- Existing Unity Catalog identity (verified 2026-11-03; values in the author's `.env`, not here): the dev workspace has an Access Connector in its own resource group, in the same subscription where our resource group goes, region westus2. The connector has a system-assigned and a user-assigned identity. The existing Unity Catalog storage credentials on it use the user-assigned identity.
- `az` on the author's machine has no default subscription, so every `az` command in docs passes `--subscription "$AZURE_SUBSCRIPTION_ID"`.
- The Storage Blob Data Contributor id was checked in T1 (Notes). The AcrPull and Key Vault Secrets User ids in E4 were written by the planner from memory; the task that uses them checks them against the Azure built-in roles documentation.
- Easy to get wrong:
  - Cross-resource-group lookup: the identity lives in another resource group, so the `existing` reference needs `scope: resourceGroup(<its RG>)`, with the RG and name taken from the resource id parameter. Its `properties.principalId` is what the role assignment needs; `principalType` is `ServicePrincipal`.
  - Role assignment scope: the identity's role must be scoped to the `tpcds` container, not to the whole storage account (DESIGN §4 table).
  - Role assignment names must be deterministic (`guid(scope, principalId, roleDefinitionId)`), or a redeploy fails with "role assignment already exists".
  - Global names (storage account, Key Vault, registry) must be globally unique and follow each service's character rules (storage: 3–24 lowercase letters and digits).

## Decisions

| Decision | Options | Chosen | Why |
|----------|---------|--------|-----|
| Container Apps in this spec | All of §4 now; shared base now, apps in milestone 1 | Shared base now, apps in milestone 1 | An app needs an image; a placeholder image is throwaway work. Author agreed 2026-11-03. Needs a DESIGN decision-log line. |
| Deployment scope | Resource-group scope (RG made by hand); subscription scope creating the RG | Subscription scope, `main.bicep` creates the RG | Keeps DESIGN's rule "Azure resources only through `infra/`". Planner's call (low risk). |
| Key Vault access model | Access policies; Azure RBAC | Azure RBAC | Current recommended model; role assignments live next to the others. Planner's call. |
| Naming | Fixed names; prefix + `uniqueString` | `prefix` parameter (default `dqr`) + `uniqueString(subscription().id, rgName)` where global uniqueness is needed | Avoids name clashes, stays stable across redeploys. Planner's call. |
| How the template is checked | Manual `az bicep build`; pytest compiles it and inspects the ARM JSON | pytest runs `az bicep build --stdout` and checks the compiled resources | Offline and free, so it runs in the normal unit suite and turns §4 into checkable facts. |
| Region | westus2; other | westus2, the default in `infra/main.bicepparam` | Author confirmed the Databricks workspace is in westus2 (2026-11-03). |
| Role assignments | All in the template; a switch to skip them for someone else to create | All in the template, no switch | Author is Owner of the subscription (2026-11-03). |
| Writing data to storage (spec 3) | Bicep grants a given principal write access on `tpcds`; write through UC-vended credentials | Optional parameter `dataWriterPrincipalId` (default empty). When set, the template gives that principal Storage Blob Data Contributor on `tpcds` | Lets spec 3 write Delta files from the author's machine; no extra UC grants. Author chose it 2026-11-03. |
| Where the writer's id comes from | Stored in `main.bicepparam`; passed on the deploy command line | Passed at deploy time (`az ad signed-in-user show --query id -o tsv`); not stored in the repo | Keeps the repo free of personal identifiers. Planner's call. |
| Access Connector | Create our own; reuse the dev workspace's | Reuse the dev one; the template creates no connector | Author's choice 2026-11-03: Unity Catalog already has storage credentials on it. Replaces the connector T1 built. Needs a DESIGN §4 change and a decision-log line. |
| Which identity gets the role | System-assigned; user-assigned; both | The connector's user-assigned identity only | The existing storage credentials use it (verified 2026-11-03). Granting both would give more access than needed. |
| How the template finds the identity | Parameter with its principal id; parameter with its resource id plus an `existing` lookup | Parameter `ucIdentityResourceId` (resource id); the template looks up `principalId` with `existing` | The resource id says what it is; the lookup follows the identity if it is ever recreated. Planner's call. |
| Where company ids live | In the repo (`main.bicepparam`, `AGENTS.md`); outside the repo | Git-ignored `.env`: `AZURE_SUBSCRIPTION_ID`, `UC_IDENTITY_RESOURCE_ID`. `main.bicepparam` reads the identity with `readEnvironmentVariable('UC_IDENTITY_RESOURCE_ID')` (no default, so a deploy without it fails). A committed `.env.example` lists the names with empty values. | Public repo, company tenant (author, 2026-11-03). |
| Guard against leaks | Review only; a test | A unit test (E8) reads the ids from `.env` and checks no tracked file contains them | Review alone misses things; this mistake already happened once in this branch. Planner's call. |

## Examples
All examples are checked by pytest on the compiled template (`az bicep build --stdout infra/main.bicep`), never by deploying.

- E1 — the template compiles
  - Given: `infra/main.bicep` and its modules
  - When: the tests compile it with `az bicep build --stdout`
  - Then: the exit code is 0 and the output is a JSON ARM template whose target scope is the subscription.
- E2 — storage for the Delta tables
  - Given: the compiled template
  - When: the tests look for storage resources
  - Then: there is exactly one `Microsoft.Storage/storageAccounts` with `isHnsEnabled: true`, and exactly one blob container named `tpcds` in it.
- E3 — Unity Catalog can reach the container, through the existing connector's identity
  - Given: the compiled template
  - When: the tests look at Access Connectors and role assignments
  - Then: there is no `Microsoft.Databricks/accessConnectors` resource. There is exactly one role assignment, apart from E7's, giving Storage Blob Data Contributor (`ba92f5b4-2d11-453d-a403-e96b0029c9fe`) scoped to the `tpcds` container; its `principalId` is the `principalId` of the user-assigned identity named by parameter `ucIdentityResourceId`, and its `principalType` is `ServicePrincipal`. The template declares no resource of type `Microsoft.ManagedIdentity/userAssignedIdentities` in the dev resource group (the lookup is `existing`, so nothing there is created or changed).
- E4 — the apps' identity
  - Given: the compiled template
  - When: the tests look at the user-assigned identity's role assignments
  - Then: it has AcrPull (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) on the registry and Key Vault Secrets User (`4633458b-17de-408a-b874-0445c86b69e6`) on the Key Vault, and no other role.
- E5 — shared base present, apps absent
  - Given: the compiled template
  - When: the tests list resource types
  - Then: it contains one Log Analytics workspace, one `Microsoft.App/managedEnvironments` sending logs to it, one container registry with SKU Basic, one Key Vault with RBAC authorisation on; and no `Microsoft.App/containerApps`.
- E6 — no secrets
  - Given: the compiled template and `infra/main.bicepparam`
  - When: the tests inspect them
  - Then: there is no `Microsoft.KeyVault/vaults/secrets` resource, and no parameter file sets a value for a parameter marked `@secure()`.
- E7 — optional write access for the author
  - Given: the compiled template
  - When: the tests look for a role assignment whose principal is the `dataWriterPrincipalId` parameter
  - Then: there is exactly one such assignment, giving Storage Blob Data Contributor on the `tpcds` container. It is deployed only when the parameter is not empty: its `condition` refers to `dataWriterPrincipalId`, and the parameter's default is `''`. `infra/main.bicepparam` does not set it.
- E8 — no company identifiers in the repo
  - Given: a `.env` at the repo root that sets `AZURE_SUBSCRIPTION_ID` and `UC_IDENTITY_RESOURCE_ID`, and optionally `AZURE_TENANT_ID`
  - When: the test reads every file listed by `git ls-files` (working-tree content)
  - Then: no file contains, case-insensitively, the subscription id, the tenant id, or the resource group name or identity name taken from `UC_IDENTITY_RESOURCE_ID`. `infra/main.bicepparam` sets `ucIdentityResourceId` only through `readEnvironmentVariable('UC_IDENTITY_RESOURCE_ID')`, and `.env.example` lists the variable names with empty values. Without a `.env` (or with a variable missing), the check of that value is skipped with a reason that names the variable; the `main.bicepparam` and `.env.example` checks still run.

## Production checklist

- [ ] Config/secrets — parameters in `infra/main.bicepparam` (region, prefix, RG name; the dev identity read from the environment); company ids only in `.env`, names in `.env.example`; no secrets anywhere.
- [ ] Errors — N/A: declarative template; compile errors are caught by E1.
- [ ] Logging — Container Apps environment sends logs to Log Analytics (E5).
- [ ] Tests — E1–E8 in the normal unit suite (offline, no cost).
- [ ] Deployment — the author loads `.env` (`set -a; source .env; set +a`), then runs `az deployment sub what-if`, then `az deployment sub create`, after an explicit go, with `--subscription "$AZURE_SUBSCRIPTION_ID"` and `--parameters infra/main.bicepparam`, passing `dataWriterPrincipalId` from `az ad signed-in-user show --query id -o tsv`. The exact commands go into `AGENTS.md`, with variable names only.
- [ ] Rollback — delete the resource group (`az group delete`); nothing else is created outside it. The role assignment for the dev identity is scoped to our container, so it goes with the group; the dev connector and identity are untouched. Note: Key Vault soft-delete keeps the vault name reserved for its retention period.
- [ ] Docs — DESIGN §2: the public-repo rule (no company identifiers; they live in `.env`); DESIGN §4: region confirmed, the Access Connector row and the "storage credential (from the Access Connector)" sentence changed to the reused dev connector, described without names; §11 milestone rows; decision-log lines for moving the apps to milestone 1 and for reusing the dev connector. `AGENTS.md` gets the one-time `az bicep install` and the deploy commands.

## Open questions
None. Q1 (region), Q2 (Azure rights), Q3 (author write access) and Q4 (company ids outside the repo, author 2026-11-03) are answered; see Decisions.

## Tasks

Generated by the create-tasks skill. The user may reorder, split or remove tasks before work starts; the executor only ticks checkboxes.

- [x] T1: Storage, Access Connector and the subscription-level entry point
  - Why: The data steps (specs 2 and 3) need only the storage account, the `tpcds` container and the Access Connector. Building them first, with `main.bicep` at subscription scope creating the resource group, sets the layout and the compile-and-inspect test pattern that T2 reuses.
  - Files: `infra/main.bicep`, `infra/main.bicepparam` (region `westus2`, prefix, RG name; no `dataWriterPrincipalId`), `infra/modules/storage.bicep` (storage account, container, Access Connector, its role assignment, the optional writer role assignment; module split is the executor's call), `tests/test_infra.py` (compiles once per session with `az bicep build --stdout infra/main.bicep`, walks nested deployments), `AGENTS.md` (one line: one-time `az bicep install` before running the tests).
  - Done when: the tests for E1, E2, E3 and E7 pass, and the Storage Blob Data Contributor role id has been checked against the Azure built-in roles documentation (finding written under Notes).
  - Out of scope: Log Analytics, Container Apps environment, registry, managed identity, Key Vault; any `az deployment` command; DESIGN edits.

- [ ] T2: Use the existing connector's identity, read from `.env`, with a leak guard
  - Why: The author chose to reuse the dev workspace's Access Connector, so the connector T1 created must go, and its user-assigned identity gets the role on `tpcds` instead (new E3). Its resource id identifies the company, so it is read from `.env` and never committed, and a test guards against leaks (E8).
  - Files: `infra/modules/storage.bicep` (remove the Access Connector and its role; add an `existing` lookup of the identity in its own resource group, split from the resource id, and one role assignment to its `principalId`, `principalType: 'ServicePrincipal'`, scoped to `tpcds`), `infra/main.bicep` (new required parameter `ucIdentityResourceId`, passed to the module), `infra/main.bicepparam` (`param ucIdentityResourceId = readEnvironmentVariable('UC_IDENTITY_RESOURCE_ID')`, no default), `.env.example` (new: `AZURE_SUBSCRIPTION_ID=`, `AZURE_TENANT_ID=`, `UC_IDENTITY_RESOURCE_ID=`, one comment line each, no values), `tests/test_infra.py` (rewrite E3's test, add E8's; read `.env` with a few lines of parsing, no new dependency).
  - Done when: the tests for E1, E2, E3, E7 and E8 pass, with the author's `.env` filled in so E8 runs its value checks instead of skipping them.
  - Out of scope: Log Analytics, Container Apps environment, registry, the apps' identity, Key Vault; DESIGN and `AGENTS.md` edits; any `az deployment` command; any value from `.env` in a tracked file, test fixture or commit message.

- [ ] T3: Shared base for the Container Apps, plus docs
  - Why: Milestone 1 deploys the router and worker onto this base, so it must exist and be checked now (E4–E6). The decisions taken in this spec change DESIGN, and the author needs the deploy and rollback commands written down.
  - Files: `infra/main.bicep`, new module(s) under `infra/modules/` (Log Analytics, Container Apps environment, registry Basic, user-assigned identity, Key Vault with RBAC, the identity's two role assignments), `tests/test_infra.py`, `docs/DESIGN.md` (§2: public-repo rule, company identifiers only in `.env`; §4: region westus2 confirmed, the Access Connector row and the "storage credential (from the Access Connector)" sentence describe the reused dev workspace connector without names, apps deployed in milestone 1; §11: rows 0.5 and 1; §13: two lines dated 2026-11-03, "Container Apps router and worker deployed in milestone 1 with the worker image; milestone 0.5 deploys the shared base" and "Reuse the dev workspace's Access Connector; its user-assigned identity gets Storage Blob Data Contributor on our container"), `AGENTS.md` (one-time `az bicep install` for the infra tests; deploy: load `.env` with `set -a; source .env; set +a`, then `az deployment sub what-if` and `az deployment sub create` with `--subscription "$AZURE_SUBSCRIPTION_ID"`, `--location westus2`, `--parameters infra/main.bicepparam` and `dataWriterPrincipalId` from `az ad signed-in-user show --query id -o tsv`, marked as costing money and needing the author's go; rollback: `az group delete`, noting Key Vault soft-delete keeps the name reserved).
  - Done when: the tests for E4, E5 and E6 pass, E8 still passes, the AcrPull and Key Vault Secrets User role ids have been checked against the Azure built-in roles documentation (finding under Notes), and DESIGN and `AGENTS.md` say what is listed under Files.
  - Out of scope: `Microsoft.App/containerApps` resources, Dockerfiles, any Key Vault secret, running any `az deployment` command.

## Notes
- T1: Storage Blob Data Contributor id `ba92f5b4-2d11-453d-a403-e96b0029c9fe` checked against learn.microsoft.com/azure/role-based-access-control/built-in-roles/storage (2026-11-03): matches.
- T1: Bicep keeps the role id in a variable, so `tests/test_infra.py` expands `variables('x')` in nested templates before searching resources. T2's tests reuse this.
- T1: `prefix` is limited to 3–10 characters in Bicep, so the storage account name (prefix + 13-character suffix) always fits 3–24 characters.
- Question (2026-11-03, after T1): the author wants to reuse the dev workspace's existing Access Connector instead of creating one. This changed E3 and DESIGN §4; the planner updated the spec.
- Finding (2026-11-03, verified with `az resource show` and `databricks storage-credentials get --profile dev`; values recorded only in the author's `.env`): the connector is in the same subscription as ours, region westus2, identity type `SystemAssigned, UserAssigned`. The existing dev storage credentials (one read-write, one read-only) both use its user-assigned identity, so only that identity gets the role on `tpcds`. `az` needed an explicit `--subscription`: the author's machine has no default subscription. Open for spec 2: reuse one of these credentials for our external location, or create our own.
