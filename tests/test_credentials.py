"""Unit tests for credential vending, against a fake Databricks client.

Nothing here calls Databricks. The fake mirrors the method names and arguments of
the real SDK: `tables.get(full_name)` and
`temporary_table_credentials.generate_temporary_table_credentials` (keyword-only
`operation` and `table_id`). A missing table raises databricks.sdk.errors.NotFound.
"""

from types import SimpleNamespace

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import TableOperation

from dqr.data.tpcds import TABLE_NAMES
from dqr.router.credentials import CredentialError, TableAccess, vend_read_credentials

FULL_NAMES = [f"dqr.sf1.{name}" for name in TABLE_NAMES]


def _location(name: str) -> str:
    return f"abfss://tpcds@acct.dfs.core.windows.net/sf1/{name}/"


class _Tables:
    def __init__(self, missing: set[str]):
        self._missing = missing

    def get(self, full_name):
        if full_name in self._missing:
            raise NotFound(f"Table '{full_name}' does not exist.")
        name = full_name.split(".")[-1]
        return SimpleNamespace(table_id=f"id-{name}", storage_location=_location(name))


class _TemporaryTableCredentials:
    def __init__(self, refused: set[str], no_azure: set[str], calls: list):
        self._refused = refused
        self._no_azure = no_azure
        self._calls = calls

    def generate_temporary_table_credentials(self, *, operation=None, table_id=None):
        self._calls.append({"operation": operation, "table_id": table_id})
        name = table_id.removeprefix("id-")
        if name in self._refused:
            raise PermissionDenied("User does not have EXTERNAL USE SCHEMA")
        if name in self._no_azure:
            return SimpleNamespace(azure_user_delegation_sas=None)
        sas = SimpleNamespace(sas_token=f"sas-token-{name}")
        return SimpleNamespace(azure_user_delegation_sas=sas)


class _Client:
    def __init__(self, missing=(), refused=(), no_azure=()):
        self.calls: list[dict] = []
        self.tables = _Tables(set(missing))
        self.temporary_table_credentials = _TemporaryTableCredentials(
            set(refused), set(no_azure), self.calls
        )


def test_e1_vends_one_access_per_table_in_order():
    client = _Client()

    accesses = vend_read_credentials(client, FULL_NAMES)

    assert [a.full_name for a in accesses] == FULL_NAMES
    for access, name in zip(accesses, TABLE_NAMES, strict=True):
        assert access.location == _location(name)
        assert access.sas_token == f"sas-token-{name}"
        assert access.vend_ms >= 0
        assert f"sas-token-{name}" not in repr(access)
        assert f"sas-token-{name}" not in str(access)
    assert len(client.calls) == 24
    assert all(call["operation"] == TableOperation.READ for call in client.calls)


def test_e2_missing_table_is_named():
    client = _Client(missing={"dqr.sf1.item"})

    with pytest.raises(CredentialError, match=r"dqr\.sf1\.item"):
        vend_read_credentials(client, FULL_NAMES)


def test_e3_refused_vending_names_table_and_grant():
    client = _Client(refused={"customer"})

    with pytest.raises(CredentialError) as error:
        vend_read_credentials(client, FULL_NAMES)

    assert "dqr.sf1.customer" in str(error.value)
    assert "EXTERNAL USE SCHEMA on dqr.sf1" in str(error.value)


def test_e4_no_azure_token_is_named():
    client = _Client(no_azure={"store_sales"})

    with pytest.raises(CredentialError, match=r"dqr\.sf1\.store_sales"):
        vend_read_credentials(client, FULL_NAMES)


def test_table_access_hides_token():
    access = TableAccess("dqr.sf1.item", "abfss://x/", "secret-token", 1.0)

    assert "secret-token" not in repr(access)
    assert "secret-token" not in str(access)
