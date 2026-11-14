"""Checks on the Bicep template: compile it offline and inspect the ARM JSON.

Nothing here deploys anything or calls Azure. `az bicep build` needs the Bicep
compiler once (`az bicep install`).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MAIN_BICEP = ROOT / "infra" / "main.bicep"
MAIN_BICEPPARAM = ROOT / "infra" / "main.bicepparam"

STORAGE_BLOB_DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
STORAGE_BLOB_DELEGATOR = "db58b8e5-c6ad-4a2a-8342-4190687cbf4a"
ACR_PULL = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
KEY_VAULT_SECRETS_USER = "4633458b-17de-408a-b874-0445c86b69e6"

ROLE_ASSIGNMENT = "Microsoft.Authorization/roleAssignments"
USER_ASSIGNED_IDENTITY = "Microsoft.ManagedIdentity/userAssignedIdentities"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _compile() -> subprocess.CompletedProcess[str]:
    az = shutil.which("az")
    assert az, "az CLI not found; the infra tests need it"
    return subprocess.run(
        [az, "bicep", "build", "--file", str(MAIN_BICEP), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def template() -> dict:
    result = _compile()
    assert result.returncode == 0, f"bicep build failed:\n{result.stderr}"
    return json.loads(result.stdout)


def _expand_variables(template: dict) -> dict:
    """Replace variables('x') in a template with the variable's value.

    Bicep keeps constants such as role ids in variables; the tests want to see them
    inside the resources that use them.
    """
    variables = template.get("variables", {})
    text = json.dumps(template)
    for _ in range(10):  # variables may refer to other variables
        before = text
        for name, value in variables.items():
            if not isinstance(value, str):
                continue
            expr = value[1:-1] if value.startswith("[") else json.dumps(value)[1:-1]
            if not value.startswith("["):
                expr = f"'{expr}'"
            text = text.replace(f"variables('{name}')", expr)
        if text == before:
            break
    return json.loads(text)


def _resources(tpl: dict):
    """Every resource in the template, including those in nested deployments."""
    resources = tpl.get("resources", [])
    if isinstance(resources, dict):  # languageVersion 2.0 keys them by symbolic name
        resources = resources.values()
    for resource in resources:
        yield resource
        nested = resource.get("properties", {}).get("template")
        if resource["type"] == "Microsoft.Resources/deployments" and nested:
            yield from _resources(_expand_variables(nested))


def _of_type(tpl: dict, resource_type: str) -> list[dict]:
    return [r for r in _resources(tpl) if r["type"] == resource_type]


def _blob_contributor_assignments(tpl: dict) -> list[dict]:
    return [
        r
        for r in _of_type(tpl, ROLE_ASSIGNMENT)
        if STORAGE_BLOB_DATA_CONTRIBUTOR in json.dumps(r)
    ]


def test_e1_template_compiles_at_subscription_scope():
    result = _compile()
    assert result.returncode == 0, f"bicep build failed:\n{result.stderr}"
    tpl = json.loads(result.stdout)
    assert "subscriptionDeploymentTemplate" in tpl["$schema"]


def test_e2_storage_account_has_hns_and_one_tpcds_container(template):
    accounts = _of_type(template, "Microsoft.Storage/storageAccounts")
    assert len(accounts) == 1
    assert accounts[0]["properties"]["isHnsEnabled"] is True

    containers = _of_type(
        template, "Microsoft.Storage/storageAccounts/blobServices/containers"
    )
    assert len(containers) == 1
    assert "tpcds" in containers[0]["name"]


def test_e3_existing_connector_identity_can_use_only_the_tpcds_container(template):
    assert _of_type(template, "Microsoft.Databricks/accessConnectors") == []
    # The dev identity is looked up (`existing`), never declared, so nothing is created
    # or changed in its resource group. Our own apps identity (E4) is a different one.
    declared = _of_type(template, USER_ASSIGNED_IDENTITY)
    assert not [r for r in declared if "ucIdentityResourceId" in json.dumps(r)]

    assignments = [
        r
        for r in _blob_contributor_assignments(template)
        if "dataWriterPrincipalId" not in json.dumps(r)
    ]
    assert len(assignments) == 1
    scope = str(assignments[0]["scope"])
    assert "containers" in scope, f"not scoped to the container: {scope}"

    properties = assignments[0]["properties"]
    assert properties["principalType"] == "ServicePrincipal"
    principal = str(properties["principalId"])
    assert "ucIdentityResourceId" in principal, f"not the dev identity: {principal}"
    assert "principalId" in principal, f"does not read its principalId: {principal}"
    assert "userAssignedIdentities" in principal, f"not an identity: {principal}"


def _read_env() -> dict[str, str]:
    """Parse the author's `.env`: `KEY=value`, optional `export `, optional quotes."""
    path = ROOT / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _repo_files() -> dict[str, str]:
    """Lower-cased text of every tracked file, plus new files not yet committed."""
    git = shutil.which("git")
    assert git, "git not found"
    listing = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout
    files = {}
    for name in filter(None, listing.split("\0")):
        path = ROOT / name
        if path.is_file():
            files[name] = path.read_bytes().decode("utf-8", errors="ignore").lower()
    return files


def _needles(variable: str, value: str) -> list[str]:
    """Strings that must not appear in the repo, taken from one `.env` value."""
    if variable not in RESOURCE_ID_VARIABLES:
        return [value]
    parts = value.strip("/").split("/")
    lowered = [p.lower() for p in parts]
    needles = [value]
    if "resourcegroups" in lowered:
        needles.append(parts[lowered.index("resourcegroups") + 1])
    needles.append(parts[-1])
    return needles


# Every variable `.env.example` must list, with an empty value.
ENV_VARIABLES = [
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "UC_IDENTITY_RESOURCE_ID",
    "UC_ACCESS_CONNECTOR_ID",
    "DQR_STORAGE_ACCOUNT",
    "DQR_CATALOG",
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_WAREHOUSE_ID",
]
# Values that identify the company, so they must not appear in any repo file. The
# others are names our code creates (storage account, default catalog) or generic.
IDENTIFYING_VARIABLES = [
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "UC_IDENTITY_RESOURCE_ID",
    "UC_ACCESS_CONNECTOR_ID",
    "DQR_CATALOG",
    "DATABRICKS_WAREHOUSE_ID",
]
# Azure resource ids: their resource group and name are checked as well.
RESOURCE_ID_VARIABLES = ["UC_IDENTITY_RESOURCE_ID", "UC_ACCESS_CONNECTOR_ID"]
DEFAULT_CATALOG = "dqr"


@pytest.mark.parametrize("variable", IDENTIFYING_VARIABLES)
def test_e8_no_company_identifier_from_env_in_the_repo(variable):
    value = _read_env().get(variable, "")
    if not value:
        pytest.skip(f"{variable} is not set in .env; nothing to check")
    if variable == "DQR_CATALOG" and value == DEFAULT_CATALOG:
        pytest.skip("DQR_CATALOG is the default name, which is public")
    leaks = sorted(
        {
            name
            for needle in _needles(variable, value)
            for name, text in _repo_files().items()
            if needle.lower() in text
        }
    )
    # Never print the value: name the variable and the files only.
    assert not leaks, f"a value from {variable} appears in: {', '.join(leaks)}"


def test_e8_bicepparam_reads_the_identity_only_from_the_environment():
    text = MAIN_BICEPPARAM.read_text()
    assert (
        "param ucIdentityResourceId = "
        "readEnvironmentVariable('UC_IDENTITY_RESOURCE_ID')" in text
    )
    assert "/subscriptions/" not in text


def test_e8_env_example_lists_the_names_with_empty_values():
    env = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    assert set(ENV_VARIABLES) <= set(env)
    assert all(env[name] == "" for name in ENV_VARIABLES)


def test_e4_apps_identity_can_pull_images_and_read_key_vault_secrets(template):
    declared = [
        r
        for r in _of_type(template, USER_ASSIGNED_IDENTITY)
        if "ucIdentityResourceId" not in json.dumps(r)
    ]
    assert len(declared) == 1

    granted = {}
    for r in _of_type(template, ROLE_ASSIGNMENT):
        principal = str(r["properties"]["principalId"])
        if (
            "userAssignedIdentities" in principal
            and "ucIdentityResourceId" not in principal
        ):
            role = GUID.search(str(r["properties"]["roleDefinitionId"]))
            assert role, f"no role id in {r['properties']['roleDefinitionId']}"
            granted[role.group(0)] = str(r["scope"])

    assert set(granted) == {ACR_PULL, KEY_VAULT_SECRETS_USER}
    assert "Microsoft.ContainerRegistry/registries" in granted[ACR_PULL]
    assert "Microsoft.KeyVault/vaults" in granted[KEY_VAULT_SECRETS_USER]


def test_e5_shared_base_is_present_and_has_no_apps(template):
    workspaces = _of_type(template, "Microsoft.OperationalInsights/workspaces")
    assert len(workspaces) == 1

    environments = _of_type(template, "Microsoft.App/managedEnvironments")
    assert len(environments) == 1
    logs = environments[0]["properties"]["appLogsConfiguration"]
    assert logs["destination"] == "log-analytics"
    assert "Microsoft.OperationalInsights/workspaces" in json.dumps(logs)

    registries = _of_type(template, "Microsoft.ContainerRegistry/registries")
    assert len(registries) == 1
    assert registries[0]["sku"]["name"] == "Basic"

    vaults = _of_type(template, "Microsoft.KeyVault/vaults")
    assert len(vaults) == 1
    assert vaults[0]["properties"]["enableRbacAuthorization"] is True

    assert _of_type(template, "Microsoft.App/containerApps") == []


def test_e6_no_secrets_in_the_template_or_the_parameter_file(template):
    assert _of_type(template, "Microsoft.KeyVault/vaults/secrets") == []

    secure = [
        name
        for name, spec in template["parameters"].items()
        if spec["type"] in ("securestring", "secureObject")
    ]
    text = MAIN_BICEPPARAM.read_text()
    assert not [name for name in secure if name in text], "a secure parameter is set"


def test_e7_writer_role_is_optional_and_on_the_container(template):
    writer = [
        r
        for r in _blob_contributor_assignments(template)
        if "dataWriterPrincipalId" in str(r["properties"]["principalId"])
    ]
    assert len(writer) == 1
    assert "dataWriterPrincipalId" in str(writer[0]["condition"])
    assert "containers" in str(writer[0]["scope"])

    assert template["parameters"]["dataWriterPrincipalId"]["defaultValue"] == ""
    assert "dataWriterPrincipalId" not in MAIN_BICEPPARAM.read_text()


def test_e14_connector_identity_can_get_a_user_delegation_key(template):
    delegators = [
        r
        for r in _of_type(template, ROLE_ASSIGNMENT)
        if STORAGE_BLOB_DELEGATOR in json.dumps(r)
    ]
    assert len(delegators) == 1
    scope = str(delegators[0]["scope"])
    assert "storageAccounts" in scope, f"not scoped to the storage account: {scope}"
    assert "containers" not in scope, f"scoped to a container: {scope}"

    properties = delegators[0]["properties"]
    assert properties["principalType"] == "ServicePrincipal"
    principal = str(properties["principalId"])
    assert "ucIdentityResourceId" in principal, f"not the dev identity: {principal}"
    assert "principalId" in principal, f"does not read its principalId: {principal}"
    assert "userAssignedIdentities" in principal, f"not an identity: {principal}"
