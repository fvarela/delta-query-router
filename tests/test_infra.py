"""Checks on the Bicep template: compile it offline and inspect the ARM JSON.

Nothing here deploys anything or calls Azure. `az bicep build` needs the Bicep
compiler once (`az bicep install`).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MAIN_BICEP = ROOT / "infra" / "main.bicep"
MAIN_BICEPPARAM = ROOT / "infra" / "main.bicepparam"

STORAGE_BLOB_DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"

ROLE_ASSIGNMENT = "Microsoft.Authorization/roleAssignments"


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


def test_e3_access_connector_can_use_only_the_tpcds_container(template):
    connectors = _of_type(template, "Microsoft.Databricks/accessConnectors")
    assert len(connectors) == 1
    assert connectors[0]["identity"]["type"] == "SystemAssigned"

    assignments = [
        r
        for r in _blob_contributor_assignments(template)
        if "dataWriterPrincipalId" not in json.dumps(r)
    ]
    assert len(assignments) == 1
    scope = str(assignments[0]["scope"])
    assert "containers" in scope, f"not scoped to the container: {scope}"
    principal = str(assignments[0]["properties"]["principalId"])
    assert "accessConnectors" in principal, f"not the Access Connector: {principal}"


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
