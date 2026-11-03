# Infra: Bicep for the shared Azure base

Status: approved

## Goal
Describe in Bicep, under `infra/`, the Azure resources the next steps need: storage for the Delta tables,
the Access Connector that Unity Catalog uses to reach that storage, and the shared base the Container
Apps will run on later. The author deploys it with one command. The two apps (`router`, `worker`) are
added in milestone 1, once a worker image exists.

## Non-goals
- The Container Apps `router` and `worker` (milestone 1).
- Dockerfiles and images.
- Unity Catalog objects (storage credential, external location, catalog, schemas): next spec, `unity-catalog-setup`.
- The Databricks service principal, and putting its secret into Key Vault (that is a manual step, done later).
- Private networking (VNet, private endpoints), CI pipelines, multiple environments.

## Context
- Source of truth: `docs/DESIGN.md` §2 (money, resources, secrets rules), §3, §4, §9 (`infra/` = `main.bicep` + modules + parameter files).
- Repo today: `src/dqr/__init__.py`, `tests/` (conftest, smoke, pytest config), `pyproject.toml` with no runtime deps. No `infra/` yet; the first task that writes a file there creates it.
- Tools verified present: `az` (`/usr/bin/az`). The standalone `bicep` CLI is not installed; `az bicep build` compiles offline once `az bicep install` has fetched the compiler.
- Invariants:
  - Nothing in this spec creates Azure resources by itself. Deploying is a separate command the author runs after an explicit go (DESIGN §2, money rule).
  - No secret values in the repo, in parameter files or in templates. Key Vault is created empty.
  - All resources in one resource group, in the Databricks workspace's region (DESIGN §4).
- The built-in role ids in E3 and E4 were written by the planner from memory and not checked here. The first task that uses them checks them against the Azure built-in roles documentation.
- Easy to get wrong:
  - Role assignment scope: the Access Connector's role must be scoped to the `tpcds` container, not to the whole storage account (DESIGN §4 table).
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
- E3 — Unity Catalog can reach the container
  - Given: the compiled template
  - When: the tests look at the Access Connector and role assignments
  - Then: there is one `Microsoft.Databricks/accessConnectors` with a system-assigned identity, and one role assignment giving that identity Storage Blob Data Contributor (`ba92f5b4-2d11-453d-a403-e96b0029c9fe`) scoped to the `tpcds` container.
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

## Production checklist

- [ ] Config/secrets — parameters in `infra/main.bicepparam` (region, prefix, RG name); no secrets anywhere.
- [ ] Errors — N/A: declarative template; compile errors are caught by E1.
- [ ] Logging — Container Apps environment sends logs to Log Analytics (E5).
- [ ] Tests — E1–E7 in the normal unit suite (offline, no cost).
- [ ] Deployment — the author runs `az deployment sub what-if`, then `az deployment sub create`, after an explicit go, passing `dataWriterPrincipalId` from `az ad signed-in-user show --query id -o tsv`. The exact commands go into `AGENTS.md`.
- [ ] Rollback — delete the resource group (`az group delete`); nothing else is created outside it. Note: Key Vault soft-delete keeps the vault name reserved for its retention period.
- [ ] Docs — DESIGN §4 region confirmed, §11 milestone rows and a decision-log line for moving the apps to milestone 1; `AGENTS.md` gets the one-time `az bicep install` and the deploy commands.

## Open questions
None. Q1 (region), Q2 (Azure rights) and Q3 (author write access) were answered on 2026-11-03; see Decisions.

## Tasks

Generated by the create-tasks skill. The user may reorder, split or remove tasks before work starts; the executor only ticks checkboxes.

- [ ] T1: Storage, Access Connector and the subscription-level entry point
  - Why: The data steps (specs 2 and 3) need only the storage account, the `tpcds` container and the Access Connector. Building them first, with `main.bicep` at subscription scope creating the resource group, sets the layout and the compile-and-inspect test pattern that T2 reuses.
  - Files: `infra/main.bicep`, `infra/main.bicepparam` (region `westus2`, prefix, RG name; no `dataWriterPrincipalId`), `infra/modules/storage.bicep` (storage account, container, Access Connector, its role assignment, the optional writer role assignment; module split is the executor's call), `tests/test_infra.py` (compiles once per session with `az bicep build --stdout infra/main.bicep`, walks nested deployments), `AGENTS.md` (one line: one-time `az bicep install` before running the tests).
  - Done when: the tests for E1, E2, E3 and E7 pass, and the Storage Blob Data Contributor role id has been checked against the Azure built-in roles documentation (finding written under Notes).
  - Out of scope: Log Analytics, Container Apps environment, registry, managed identity, Key Vault; any `az deployment` command; DESIGN edits.

- [ ] T2: Shared base for the Container Apps, plus docs
  - Why: Milestone 1 deploys the router and worker onto this base, so it must exist and be checked now (E4–E6). The decision to move the apps to milestone 1 and the confirmed region change DESIGN, and the author needs the deploy and rollback commands written down.
  - Files: `infra/main.bicep`, new module(s) under `infra/modules/` (Log Analytics, Container Apps environment, registry Basic, user-assigned identity, Key Vault with RBAC, the identity's two role assignments), `tests/test_infra.py`, `docs/DESIGN.md` (§4: region westus2 confirmed, apps deployed in milestone 1; §11: rows 0.5 and 1; §13: decision-log line dated 2026-11-03 "Container Apps router and worker deployed in milestone 1 with the worker image; milestone 0.5 deploys the shared base"), `AGENTS.md` (deploy commands: `az deployment sub what-if` and `az deployment sub create` with `dataWriterPrincipalId` from `az ad signed-in-user show --query id -o tsv`, marked as costing money and needing the author's go; rollback: `az group delete`, noting Key Vault soft-delete keeps the name reserved).
  - Done when: the tests for E4, E5 and E6 pass, the AcrPull and Key Vault Secrets User role ids have been checked against the Azure built-in roles documentation (finding under Notes), and DESIGN and AGENTS.md say what is listed under Files.
  - Out of scope: `Microsoft.App/containerApps` resources, Dockerfiles, any Key Vault secret, running any `az deployment` command.

## Notes
