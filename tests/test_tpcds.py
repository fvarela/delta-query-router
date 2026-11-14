import pyarrow as pa
import pytest
from deltalake import DeltaTable, write_deltalake

from dqr.data import tpcds
from dqr.data.tpcds import (
    TABLE_NAMES,
    DuckDbSource,
    WriteError,
    load_write_settings,
    write_tables,
)
from dqr.data.unity_catalog import SettingsError


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
