"""Vend short-lived, read-only table credentials from Unity Catalog.

The SAS token is a secret: it is hidden from `repr` and `str` and never logged.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import TableOperation


class CredentialError(Exception):
    """Vending failed; the message names the table."""


@dataclass(frozen=True)
class TableAccess:
    full_name: str
    location: str
    sas_token: str = field(repr=False)
    vend_ms: float = 0.0

    def __str__(self) -> str:
        return repr(self)


def vend_read_credentials(client: Any, full_names: Sequence[str]) -> list[TableAccess]:
    """One READ credential per table, in the order given."""
    return [_vend_one(client, full_name) for full_name in full_names]


def _vend_one(client: Any, full_name: str) -> TableAccess:
    started = time.perf_counter()
    try:
        table = client.tables.get(full_name)
    except NotFound as error:
        raise CredentialError(f"Table {full_name} does not exist.") from error
    generate = client.temporary_table_credentials.generate_temporary_table_credentials
    try:
        response = generate(operation=TableOperation.READ, table_id=table.table_id)
    except PermissionDenied as error:
        schema = full_name.rsplit(".", 1)[0]
        raise CredentialError(
            f"Not allowed to read {full_name}: the caller needs "
            f"EXTERNAL USE SCHEMA on {schema}."
        ) from error
    sas = response.azure_user_delegation_sas
    if sas is None or not sas.sas_token:
        raise CredentialError(f"No Azure SAS token returned for {full_name}.")
    vend_ms = (time.perf_counter() - started) * 1000
    return TableAccess(full_name, table.storage_location, sas.sas_token, vend_ms)
