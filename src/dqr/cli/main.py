"""Dev tool menu: a thin layer over the plain functions in `dqr.data`.

`run` holds the logic and takes its prompts, console and client factory as arguments,
so tests can fake them. `main` wires in the real ones.
"""

import questionary
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from deltalake.exceptions import DeltaError
from duckdb import Error as DuckDbError
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dqr.data.tpcds import (
    DuckDbSource,
    RegisterError,
    WriteError,
    load_register_settings,
    load_write_settings,
    register_tables,
    write_tables,
)
from dqr.data.unity_catalog import (
    SettingsError,
    SetupError,
    Step,
    TeardownError,
    load_settings,
    setup,
    teardown,
)

SETUP = "setup"
TEARDOWN = "teardown"
WRITE = "write"
REGISTER = "register"
QUIT = "quit"

TPCDS_SCALE_FACTOR = 1
TPCDS_SCHEMA = "sf1"

# Errors shown as one message. ValueError is what the SDK raises when it cannot
# configure a login (for example an unknown profile).
EXPECTED_ERRORS = (
    SettingsError,
    SetupError,
    TeardownError,
    WriteError,
    RegisterError,
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


def run(choose, ask, confirm, console: Console, make_client) -> None:
    """Show the menu until the author quits.

    `choose()` returns SETUP, TEARDOWN, WRITE, REGISTER, QUIT or None (cancelled);
    `ask(question)` returns the typed text or None; `confirm(question)` returns True
    on yes and False or None otherwise; `make_client()` builds the Databricks client.
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
                questionary.Choice("Quit", QUIT),
            ],
        ).ask()

    def ask(question):
        return questionary.text(question).ask()

    def confirm(question):
        return questionary.confirm(question, default=False).ask()

    run(choose, ask, confirm, Console(), WorkspaceClient)
