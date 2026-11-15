"""Read Delta tables with DuckDB `delta_scan`, one view per table.

Each table gets its own Azure secret scoped to its location, because a vended SAS
token only covers its own table. SAS tokens are secrets: run errors through
`redact` before showing them.
"""

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

import duckdb

from dqr.router.credentials import TableAccess


class ReaderError(Exception):
    """The reader cannot be set up; the message names the table."""


@dataclass(frozen=True)
class QueryResult:
    rows: list[tuple]
    ms: float


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _split(full_name: str) -> tuple[str, str, str]:
    catalog, schema, table = full_name.split(".")
    return catalog, schema, table


def register_secrets(conn: Any, accesses: Sequence[TableAccess]) -> None:
    """Load the extensions, attach one in-memory database per catalog, and create
    one Azure secret per `abfss://` table, scoped to its location as given."""
    conn.execute("INSTALL delta")
    conn.execute("INSTALL azure")
    conn.execute("LOAD delta")
    conn.execute("LOAD azure")
    attached: set[str] = set()
    for access in accesses:
        catalog = _split(access.full_name)[0]
        if catalog not in attached:
            conn.execute(f"ATTACH ':memory:' AS {_ident(catalog)}")
            attached.add(catalog)
        if not access.location.startswith("abfss://"):
            continue
        if not access.sas_token:
            raise ReaderError(f"No SAS token for {access.full_name}.")
        account = (urlparse(access.location).hostname or "").split(".")[0]
        connection_string = (
            f"BlobEndpoint=https://{account}.blob.core.windows.net;"
            f"SharedAccessSignature={access.sas_token}"
        )
        name = re.sub(r"\W", "_", access.full_name)
        conn.execute(
            f"CREATE SECRET {_ident(name)} (TYPE azure, "
            f"CONNECTION_STRING {_literal(connection_string)}, "
            f"SCOPE {_literal(access.location)})"
        )


def create_views(conn: Any, accesses: Sequence[TableAccess]) -> None:
    """One view per table over `delta_scan`. DuckDB reads the Delta log here."""
    for access in accesses:
        catalog, schema, table = _split(access.full_name)
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_ident(catalog)}.{_ident(schema)}")
        conn.execute(
            f"CREATE VIEW {_ident(catalog)}.{_ident(schema)}.{_ident(table)} AS "
            f"SELECT * FROM delta_scan({_literal(access.location)})"
        )


def connect(accesses: Sequence[TableAccess]) -> Any:
    """A DuckDB connection where every table is a view, reachable as `<table>` and
    as `<catalog>.<schema>.<table>` (the first table's catalog and schema)."""
    conn = duckdb.connect()
    try:
        register_secrets(conn, accesses)
        create_views(conn, accesses)
        if accesses:
            catalog, schema, _ = _split(accesses[0].full_name)
            conn.execute(f"USE {_ident(catalog)}.{_ident(schema)}")
    except Exception:
        conn.close()
        raise
    return conn


def run_query(conn: Any, sql: str) -> QueryResult:
    started = time.perf_counter()
    rows = conn.execute(sql).fetchall()
    return QueryResult(rows, (time.perf_counter() - started) * 1000)


def redact(message: str, tokens: Sequence[str]) -> str:
    """Replace each token (plain and URL-encoded) and any `sig=` value with `***`."""
    forms: set[str] = set()
    for token in tokens:
        if token:
            forms.update(
                {token, quote(token), quote(token, safe=""), quote_plus(token)}
            )
    for form in sorted(forms, key=len, reverse=True):
        message = message.replace(form, "***")
    return re.sub(r"(?i)(sig=)[^&\s'\"]+", r"\1***", message)
