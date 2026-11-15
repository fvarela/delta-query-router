"""Dev tool menu: a thin layer over the plain functions in `dqr.data`.

`run` holds the logic and takes its prompts, console and client factory as arguments,
so tests can fake them. `main` wires in the real ones.
"""

import os

import duckdb
import questionary
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from deltalake.exceptions import DeltaError
from duckdb import Error as DuckDbError
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dqr.data.tpcds import (
    TABLE_NAMES,
    DuckDbSource,
    RegisterError,
    WriteError,
    load_register_settings,
    load_write_settings,
    register_tables,
    write_tables,
)
from dqr.data.unity_catalog import (
    DEFAULT_CATALOG,
    SettingsError,
    SetupError,
    Step,
    TeardownError,
    load_settings,
    setup,
    teardown,
)
from dqr.router.credentials import CredentialError, vend_read_credentials
from dqr.worker.reader import ReaderError, connect, redact, run_query

SETUP = "setup"
TEARDOWN = "teardown"
WRITE = "write"
REGISTER = "register"
READ = "read"
QUIT = "quit"

TPCDS_SCALE_FACTOR = 1
TPCDS_SCHEMA = "sf1"


class ReadError(Exception):
    """A read failed; the message has already been redacted."""


# Errors shown as one message. ValueError is what the SDK raises when it cannot
# configure a login (for example an unknown profile).
EXPECTED_ERRORS = (
    SettingsError,
    SetupError,
    TeardownError,
    WriteError,
    RegisterError,
    ReadError,
    DeltaError,
    DuckDbError,
    DatabricksError,
    ValueError,
)


def show_report(console: Console, report: list[Step]) -> None:
    table = Table("Type", "Name", "Status")
    for step in report:
        table.add_row(step.kind, step.name, step.status)
    console.print(table)


def _unity_catalog(action, ask, make_client) -> list[Step]:
    settings = load_settings()  # fails before any Databricks call
    client = make_client()
    if action == SETUP:
        return setup(client, settings)
    typed = ask(
        f"Type the catalog name ({settings.catalog}) to delete what setup created:"
    )
    return teardown(client, settings, typed or "")


def _write_tpcds() -> list[Step]:
    settings = load_write_settings()  # fails before any DuckDB or Azure call
    source = DuckDbSource(TPCDS_SCALE_FACTOR)
    return write_tables(source, settings.root, TPCDS_SCHEMA, settings.storage_options)


def _register_tpcds(confirm, make_client) -> list[Step] | None:
    settings = load_register_settings()  # fails before the question
    if not confirm(
        "Registering the tables runs SQL on the Databricks warehouse, which costs "
        "money. Continue?"
    ):
        return None
    return register_tables(make_client(), settings, TPCDS_SCHEMA)


def _read_tpcds(console: Console, make_client) -> None:
    catalog = os.environ.get("DQR_CATALOG", "").strip() or DEFAULT_CATALOG
    names = [f"{catalog}.{TPCDS_SCHEMA}.{table}" for table in TABLE_NAMES]
    accesses = []
    conn = None
    try:
        accesses = vend_read_credentials(make_client(), names)
        conn = connect(accesses)
        report = Table("Table", "Rows", "Vending ms", "Count ms")
        for access in accesses:
            table = access.full_name.rsplit(".", 1)[-1]
            result = run_query(
                conn, f'SELECT count(*) FROM "{catalog}"."{TPCDS_SCHEMA}"."{table}"'
            )
            report.add_row(
                table,
                str(result.rows[0][0]),
                f"{access.vend_ms:.0f}",
                f"{result.ms:.0f}",
            )
        extensions = run_query(
            conn,
            "SELECT extension_name, extension_version FROM duckdb_extensions() "
            "WHERE extension_name IN ('delta', 'azure') ORDER BY extension_name",
        ).rows
    except (
        CredentialError,
        ReaderError,
        DuckDbError,
        DatabricksError,
        ValueError,
    ) as e:
        # The message may echo a SAS token: redact before it is shown.
        raise ReadError(redact(str(e), [a.sas_token for a in accesses])) from None
    finally:
        if conn is not None:
            conn.close()
    console.print(report)
    versions = ", ".join(f"{name} {version}" for name, version in extensions)
    console.print(Text(f"DuckDB {duckdb.__version__}; extensions: {versions}"))


def run(choose, ask, confirm, console: Console, make_client) -> None:
    """Show the menu until the author quits.

    `choose()` returns SETUP, TEARDOWN, WRITE, REGISTER, READ, QUIT or None
    (cancelled); `ask(question)` returns the typed text or None; `confirm(question)`
    returns True on yes and False or None otherwise; `make_client()` builds the
    Databricks client.
    """
    while True:
        action = choose()
        if action in (None, QUIT):
            return
        try:
            if action == WRITE:
                report = _write_tpcds()
            elif action == REGISTER:
                report = _register_tpcds(confirm, make_client)
            elif action == READ:
                report = _read_tpcds(console, make_client)
            else:
                report = _unity_catalog(action, ask, make_client)
        except EXPECTED_ERRORS as error:
            # Text(), not a string: an error message must not be read as markup.
            console.print(Text(f"Error: {error}", style="red"))
        else:
            if report is not None:
                show_report(console, report)


def main() -> None:
    def choose():
        return questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Set up Unity Catalog", SETUP),
                questionary.Choice("Tear down Unity Catalog", TEARDOWN),
                questionary.Choice("Write TPC-DS SF1 data", WRITE),
                questionary.Choice("Register TPC-DS SF1 tables", REGISTER),
                questionary.Choice("Read TPC-DS SF1 with DuckDB", READ),
                questionary.Choice("Quit", QUIT),
            ],
        ).ask()

    def ask(question):
        return questionary.text(question).ask()

    def confirm(question):
        return questionary.confirm(question, default=False).ask()

    run(choose, ask, confirm, Console(), WorkspaceClient)
