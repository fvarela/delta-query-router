from types import SimpleNamespace

import pyarrow as pa
import pytest
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import (
    ServiceError,
    StatementResponse,
    StatementState,
    StatementStatus,
)
from deltalake import DeltaTable, write_deltalake

from dqr.data import tpcds
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
from dqr.data.unity_catalog import MARKER, SettingsError


class FakeSource:
    """Same interface as DuckDbSource, over small in-memory Arrow tables."""

    def __init__(self):
        self.tables = {
            name: pa.table({"id": [1, 2, 3], "label": [f"{name}-a", f"{name}-b", None]})
            for name in TABLE_NAMES
        }

    def table_names(self):
        return list(self.tables)

    def row_count(self, name):
        return self.tables[name].num_rows

    def reader(self, name):
        return pa.RecordBatchReader.from_batches(
            self.tables[name].schema, self.tables[name].to_batches(max_chunksize=2)
        )


def delta_version(root, schema, name):
    return DeltaTable(str(root / schema / name)).version()


def test_e1_write_to_an_empty_root(tmp_path):
    source = FakeSource()

    report = write_tables(source, str(tmp_path), "sf1")

    assert [step.name for step in report] == [f"sf1.{name}" for name in TABLE_NAMES]
    assert {step.status for step in report} == {"written, 3 rows"}
    for name in TABLE_NAMES:
        written = DeltaTable(str(tmp_path / "sf1" / name)).to_pyarrow_table()
        assert written.sort_by("id").equals(source.tables[name])


def test_e2_writing_again_changes_nothing(tmp_path):
    write_tables(FakeSource(), str(tmp_path), "sf1")

    report = write_tables(FakeSource(), str(tmp_path), "sf1")

    assert [step.status for step in report] == ["exists"] * 24
    assert [delta_version(tmp_path, "sf1", name) for name in TABLE_NAMES] == [0] * 24


def test_e3_a_partly_written_root(tmp_path):
    source = FakeSource()
    write_deltalake(str(tmp_path / "sf1" / "store_sales"), source.tables["store_sales"])

    report = write_tables(source, str(tmp_path), "sf1")

    status = {step.name: step.status for step in report}
    assert status["sf1.store_sales"] == "exists"
    assert delta_version(tmp_path, "sf1", "store_sales") == 0
    assert list(status.values()).count("written, 3 rows") == 23


def test_e4_row_count_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(tpcds, "_logged_row_count", lambda path, options: 99)

    with pytest.raises(WriteError) as error:
        write_tables(FakeSource(), str(tmp_path), "sf1")

    message = str(error.value)
    assert "sf1.call_center" in message
    assert "3" in message and "99" in message
    assert not (tmp_path / "sf1" / TABLE_NAMES[1]).exists()


def test_e5_the_duckdb_source(tmp_path):
    source = DuckDbSource(0.01)

    assert sorted(source.table_names()) == sorted(TABLE_NAMES)
    assert source.row_count("store_sales") >= 1

    write_tables(source, str(tmp_path), "sf1")

    allowed = {"integer", "long", "string", "date"}
    for name in TABLE_NAMES:
        table = DeltaTable(str(tmp_path / "sf1" / name))
        for field in table.schema().fields:
            type_name = getattr(field.type, "type", str(field.type))
            assert type_name in allowed or type_name.startswith("decimal("), (
                f"{name}.{field.name}: {type_name}"
            )
    store_sales = DeltaTable(str(tmp_path / "sf1" / "store_sales"))
    assert store_sales.to_pyarrow_table().num_rows >= 1


@pytest.mark.parametrize("missing", ["DQR_STORAGE_ACCOUNT", "AZURE_TENANT_ID"])
def test_e10_write_settings_missing(missing):
    env = {"DQR_STORAGE_ACCOUNT": "acct", "AZURE_TENANT_ID": "tenant-secret"}
    env[missing] = " "

    with pytest.raises(SettingsError) as error:
        load_write_settings(env)

    assert missing in str(error.value)
    assert "tenant-secret" not in str(error.value)
    assert "acct" not in str(error.value)


def test_e10_write_settings_loaded():
    settings = load_write_settings(
        {"DQR_STORAGE_ACCOUNT": "acct", "AZURE_TENANT_ID": "tenant"}
    )

    assert settings.root == "abfss://tpcds@acct.dfs.core.windows.net/"
    assert settings.storage_options == {
        "azure_use_azure_cli": "true",
        "azure_tenant_id": "tenant",
    }


# Registration, against a fake Databricks client.

REGISTER_ENV = {"DQR_STORAGE_ACCOUNT": "acct", "DATABRICKS_WAREHOUSE_ID": "wh"}


def no_sleep(seconds):
    pass


def response(statement_id, state, message=None):
    error = ServiceError(message=message) if message else None
    return StatementResponse(
        statement_id=statement_id, status=StatementStatus(state=state, error=error)
    )


class FakeTables:
    def __init__(self, calls):
        self.calls = calls
        self.existing: dict[str, str | None] = {}  # full name -> comment

    def get(self, full_name):
        self.calls.append(("tables.get", full_name))
        if full_name not in self.existing:
            raise NotFound(f"table {full_name} does not exist")
        return SimpleNamespace(comment=self.existing[full_name])


class FakeStatements:
    """Each statement walks through the states scripted for its table."""

    def __init__(self, calls, tables):
        self.calls = calls
        self.tables = tables
        self.scripts: dict[str, list] = {}  # table name -> [(state, message), ...]
        self._left: dict[str, list] = {}

    def _next(self, table):
        left = self._left.setdefault(table, list(self.scripts.get(table, [])))
        state, message = left.pop(0) if left else (StatementState.SUCCEEDED, None)
        if state == StatementState.SUCCEEDED:
            self.tables.existing[f"dqr.sf1.{table}"] = MARKER
        return response(table, state, message)

    def execute_statement(self, statement, warehouse_id, *, wait_timeout=None):
        self.calls.append(("execute", warehouse_id, statement))
        table = statement.split("`.`")[2].split("`")[0]
        return self._next(table)

    def get_statement(self, statement_id):
        self.calls.append(("get_statement", statement_id))
        return self._next(statement_id)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.tables = FakeTables(self.calls)
        self.statement_execution = FakeStatements(self.calls, self.tables)

    @property
    def statements(self):
        return [call for call in self.calls if call[0] == "execute"]


@pytest.fixture
def settings():
    return load_register_settings(REGISTER_ENV)


def test_e6_register_into_an_empty_schema(settings):
    client = FakeClient()

    report = register_tables(client, settings, "sf1", sleep=no_sleep)

    expected = [
        (
            "execute",
            "wh",
            f"CREATE TABLE `dqr`.`sf1`.`{name}` USING DELTA COMMENT '{MARKER}' "
            f"LOCATION 'abfss://tpcds@acct.dfs.core.windows.net/sf1/{name}/'",
        )
        for name in TABLE_NAMES
    ]
    assert client.statements == expected
    assert [step.name for step in report] == [f"dqr.sf1.{name}" for name in TABLE_NAMES]
    assert {step.status for step in report} == {"registered"}


def test_e7_register_again_changes_nothing(settings):
    client = FakeClient()
    for name in TABLE_NAMES:
        client.tables.existing[f"dqr.sf1.{name}"] = MARKER

    report = register_tables(client, settings, "sf1", sleep=no_sleep)

    assert client.statements == []
    assert [step.status for step in report] == ["exists"] * 24


def test_e8_an_unmarked_table_stops_registration(settings):
    client = FakeClient()
    client.tables.existing["dqr.sf1.item"] = "someone else's table"

    with pytest.raises(RegisterError) as error:
        register_tables(client, settings, "sf1", sleep=no_sleep)

    assert "dqr.sf1.item" in str(error.value)
    assert not any(call[0] in ("execute", "get_statement") for call in client.calls)


def test_e9a_statement_states_are_polled(settings):
    client = FakeClient()
    client.statement_execution.scripts["call_center"] = [
        (StatementState.PENDING, None),
        (StatementState.RUNNING, None),
        (StatementState.SUCCEEDED, None),
    ]

    report = register_tables(client, settings, "sf1", sleep=no_sleep)

    assert report[0].status == "registered"
    polls = [call for call in client.calls if call[0] == "get_statement"]
    assert polls == [("get_statement", "call_center")] * 2


def test_e9b_a_failed_statement_stops_and_a_rerun_resumes(settings):
    client = FakeClient()
    client.statement_execution.scripts["customer"] = [
        (StatementState.FAILED, "location is not accessible")
    ]

    with pytest.raises(RegisterError) as error:
        register_tables(client, settings, "sf1", sleep=no_sleep)

    assert "dqr.sf1.customer" in str(error.value)
    assert "location is not accessible" in str(error.value)
    sent = [call[2].split("`.`")[2].split("`")[0] for call in client.statements]
    assert sent == list(TABLE_NAMES[: TABLE_NAMES.index("customer") + 1])

    report = register_tables(client, settings, "sf1", sleep=no_sleep)

    status = {step.name: step.status for step in report}
    assert [s for s in status.values()].count("exists") == 4
    assert status["dqr.sf1.customer"] == "registered"


@pytest.mark.parametrize("missing", ["DQR_STORAGE_ACCOUNT", "DATABRICKS_WAREHOUSE_ID"])
def test_e10_register_settings_missing(missing):
    env = {"DQR_STORAGE_ACCOUNT": "acct-secret", "DATABRICKS_WAREHOUSE_ID": "wh-secret"}
    env[missing] = ""

    with pytest.raises(SettingsError) as error:
        load_register_settings(env)

    assert missing in str(error.value)
    assert "acct-secret" not in str(error.value)
    assert "wh-secret" not in str(error.value)


def test_e10_register_settings_catalog():
    assert load_register_settings(REGISTER_ENV).catalog == "dqr"
    env = {**REGISTER_ENV, "DQR_CATALOG": "mine"}
    assert load_register_settings(env).catalog == "mine"
