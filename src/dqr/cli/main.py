"""Dev tool menu: a thin layer over the plain functions in `dqr.data`.

`run` holds the logic and takes its prompts, console and client factory as arguments,
so tests can fake them. `main` wires in the real ones.
"""

import questionary
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from rich.console import Console
from rich.table import Table
from rich.text import Text

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
QUIT = "quit"

# Errors shown as one message. ValueError is what the SDK raises when it cannot
# configure a login (for example an unknown profile).
EXPECTED_ERRORS = (
    SettingsError,
    SetupError,
    TeardownError,
    DatabricksError,
    ValueError,
)


def show_report(console: Console, report: list[Step]) -> None:
    table = Table("Type", "Name", "Status")
    for step in report:
        table.add_row(step.kind, step.name, step.status)
    console.print(table)


def run(choose, ask, console: Console, make_client) -> None:
    """Show the menu until the author quits.

    `choose()` returns SETUP, TEARDOWN, QUIT or None (cancelled); `ask(question)`
    returns the typed text or None; `make_client()` builds the Databricks client.
    """
    while True:
        action = choose()
        if action in (None, QUIT):
            return
        try:
            settings = load_settings()  # fails before any Databricks call
            client = make_client()
            if action == SETUP:
                report = setup(client, settings)
            else:
                typed = ask(
                    f"Type the catalog name ({settings.catalog}) to delete "
                    "what setup created:"
                )
                report = teardown(client, settings, typed or "")
        except EXPECTED_ERRORS as error:
            # Text(), not a string: an error message must not be read as markup.
            console.print(Text(f"Error: {error}", style="red"))
        else:
            show_report(console, report)


def main() -> None:
    def choose():
        return questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Set up Unity Catalog", SETUP),
                questionary.Choice("Tear down Unity Catalog", TEARDOWN),
                questionary.Choice("Quit", QUIT),
            ],
        ).ask()

    def ask(question):
        return questionary.text(question).ask()

    run(choose, ask, Console(), WorkspaceClient)
