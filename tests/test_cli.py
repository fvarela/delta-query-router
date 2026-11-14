"""Tests of the dev tool menu: dispatch, report and error display.

The prompts are faked and Databricks is never called: `setup`, `teardown`,
`load_settings` and the TPC-DS functions are replaced, and the client factory is a stub.
"""

import io

import pytest
from databricks.sdk.errors import PermissionDenied
from deltalake.exceptions import DeltaError
from rich.console import Console

from dqr.cli import main as cli
from dqr.data.tpcds import RegisterError, RegisterSettings, WriteError, WriteSettings
from dqr.data.unity_catalog import (
    Settings,
    SettingsError,
    SetupError,
    Step,
    TeardownError,
)

SETTINGS = Settings(
    access_connector_id="connector-id",
    identity_resource_id="identity-id",
    storage_account="examplestorage",
    catalog="dqr",
)
WRITE_SETTINGS = WriteSettings(storage_account="examplestorage", tenant_id="tenant")
REGISTER_SETTINGS = RegisterSettings(
    storage_account="examplestorage", warehouse_id="wh", catalog="dqr"
)
CLIENT = object()
REPORT = [
    Step("storage credential", "dqr-storage", "created"),
    Step("schema", "dqr.sf1", "exists"),
]


class Session:
    """Scripted answers for one run of the menu, and everything it printed."""

    def __init__(self, choices, typed=(), confirmed=()):
        self._choices = iter(choices)
        self._typed = iter(typed)
        self._confirmed = iter(confirmed)
        self.questions = []
        self.confirmations = []
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=100, color_system=None)
        self.clients_built = 0

    def choose(self):
        return next(self._choices)

    def ask(self, question):
        self.questions.append(question)
        return next(self._typed)

    def confirm(self, question):
        self.confirmations.append(question)
        return next(self._confirmed)

    def make_client(self):
        self.clients_built += 1
        return CLIENT

    def run(self):
        cli.run(self.choose, self.ask, self.confirm, self.console, self.make_client)
        return self.output.getvalue()


@pytest.fixture
def calls(monkeypatch):
    """Replace the three functions the menu calls, and record how they are called."""
    log = []
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)

    def fake_setup(client, settings):
        log.append(("setup", client, settings))
        return REPORT

    def fake_teardown(client, settings, confirmation):
        log.append(("teardown", client, settings, confirmation))
        return REPORT

    monkeypatch.setattr(cli, "setup", fake_setup)
    monkeypatch.setattr(cli, "teardown", fake_teardown)
    return log


def test_setup_choice_calls_setup_and_shows_the_report(calls):
    session = Session([cli.SETUP, cli.QUIT])

    output = session.run()

    assert calls == [("setup", CLIENT, SETTINGS)]
    for text in ("dqr-storage", "created", "dqr.sf1", "exists"):
        assert text in output


def test_teardown_choice_asks_for_the_catalog_name_and_passes_what_was_typed(calls):
    session = Session([cli.TEARDOWN, cli.QUIT], typed=["dqr"])

    session.run()

    assert calls == [("teardown", CLIENT, SETTINGS, "dqr")]
    assert len(session.questions) == 1
    assert "dqr" in session.questions[0]


def test_a_cancelled_confirmation_is_passed_on_as_empty_text(calls):
    session = Session([cli.TEARDOWN, cli.QUIT], typed=[None])

    session.run()

    assert calls == [("teardown", CLIENT, SETTINGS, "")]


@pytest.mark.parametrize("choice", [cli.QUIT, None])
def test_quit_or_cancel_calls_nothing(calls, choice):
    session = Session([choice])

    session.run()

    assert calls == []
    assert session.clients_built == 0


@pytest.mark.parametrize(
    "error",
    [
        SetupError("storage credential dqr-storage already exists"),
        TeardownError("the typed confirmation does not match"),
        PermissionDenied("User does not have CREATE STORAGE CREDENTIAL"),
    ],
)
def test_an_error_is_shown_as_one_message_and_the_menu_goes_on(
    monkeypatch, calls, error
):
    def failing(*args):
        raise error

    monkeypatch.setattr(cli, "setup", failing)
    monkeypatch.setattr(cli, "teardown", failing)
    session = Session([cli.SETUP, cli.TEARDOWN, cli.QUIT], typed=["dqr"])

    output = session.run()  # does not raise: the menu survives the errors

    assert output.count(str(error)) == 2
    assert "Traceback" not in output


def test_missing_settings_are_shown_before_any_client_is_built(monkeypatch, calls):
    def missing():
        raise SettingsError("missing settings: DQR_STORAGE_ACCOUNT")

    monkeypatch.setattr(cli, "load_settings", missing)
    session = Session([cli.SETUP, cli.QUIT])

    output = session.run()

    assert "missing settings: DQR_STORAGE_ACCOUNT" in output
    assert session.clients_built == 0
    assert calls == []


# TPC-DS actions (E11).

SOURCE = object()
WRITE_REPORT = [Step("table", "sf1.store_sales", "written, 28810 rows")]
REGISTER_REPORT = [Step("table", "dqr.sf1.store_sales", "registered")]


@pytest.fixture
def tpcds_calls(monkeypatch):
    """Replace what the two TPC-DS actions call, and record how they are called."""
    log = []
    monkeypatch.setattr(cli, "load_write_settings", lambda: WRITE_SETTINGS)
    monkeypatch.setattr(cli, "load_register_settings", lambda: REGISTER_SETTINGS)

    def fake_source(scale_factor):
        log.append(("source", scale_factor))
        return SOURCE

    def fake_write(source, root, schema, storage_options):
        log.append(("write", source, root, schema, storage_options))
        return WRITE_REPORT

    def fake_register(client, settings, schema):
        log.append(("register", client, settings, schema))
        return REGISTER_REPORT

    monkeypatch.setattr(cli, "DuckDbSource", fake_source)
    monkeypatch.setattr(cli, "write_tables", fake_write)
    monkeypatch.setattr(cli, "register_tables", fake_register)
    return log


def test_e11_write_choice_writes_sf1_without_asking(tpcds_calls):
    session = Session([cli.WRITE, cli.QUIT])

    output = session.run()

    assert tpcds_calls == [
        ("source", 1),
        (
            "write",
            SOURCE,
            "abfss://tpcds@examplestorage.dfs.core.windows.net/",
            "sf1",
            WRITE_SETTINGS.storage_options,
        ),
    ]
    assert session.confirmations == []
    assert session.clients_built == 0
    assert "written, 28810 rows" in output


def test_e11_register_asks_first_and_registers_on_yes(tpcds_calls):
    session = Session([cli.REGISTER, cli.QUIT], confirmed=[True])

    output = session.run()

    assert tpcds_calls == [("register", CLIENT, REGISTER_SETTINGS, "sf1")]
    assert len(session.confirmations) == 1
    assert "warehouse" in session.confirmations[0]
    assert "money" in session.confirmations[0]
    assert "registered" in output


@pytest.mark.parametrize("answer", [False, None])
def test_e11_register_calls_nothing_on_no_or_cancel(tpcds_calls, answer):
    session = Session([cli.REGISTER, cli.QUIT], confirmed=[answer])

    session.run()

    assert tpcds_calls == []
    assert session.clients_built == 0


@pytest.mark.parametrize(
    "error",
    [
        WriteError("table sf1.call_center: the Delta log has 99 rows"),
        RegisterError("table dqr.sf1.customer: location is not accessible"),
        DeltaError("Failed to write to storage"),
    ],
)
def test_e11_tpcds_errors_are_shown_as_one_message(monkeypatch, tpcds_calls, error):
    def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "write_tables", failing)
    monkeypatch.setattr(cli, "register_tables", failing)
    session = Session([cli.WRITE, cli.REGISTER, cli.QUIT], confirmed=[True])

    output = session.run()  # does not raise: the menu survives the errors

    assert output.count(str(error)) == 2
    assert "Traceback" not in output


def test_e11_missing_settings_are_shown_before_any_question_or_client(
    monkeypatch, tpcds_calls
):
    def missing():
        raise SettingsError("missing settings: DATABRICKS_WAREHOUSE_ID")

    monkeypatch.setattr(cli, "load_register_settings", missing)
    session = Session([cli.REGISTER, cli.QUIT])

    output = session.run()

    assert "missing settings: DATABRICKS_WAREHOUSE_ID" in output
    assert session.confirmations == []
    assert session.clients_built == 0
    assert tpcds_calls == []
