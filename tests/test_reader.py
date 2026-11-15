"""Unit tests for the DuckDB reader. Nothing here reads from Azure.

Tables are local Delta folders written with `deltalake` into a temporary folder.
"""

from urllib.parse import quote, quote_plus

import duckdb
import pyarrow as pa
import pytest
from deltalake import write_deltalake

from dqr.router.credentials import TableAccess
from dqr.worker.reader import (
    ReaderError,
    connect,
    redact,
    register_secrets,
    run_query,
)

ACCOUNT_ROOT = "abfss://tpcds@acct.dfs.core.windows.net/sf1"


def _local_access(tmp_path, name: str, data: dict) -> TableAccess:
    path = tmp_path / name
    write_deltalake(str(path), pa.table(data))
    return TableAccess(f"dqr.sf1.{name}", str(path), "")


def _secrets(conn) -> list[tuple]:
    return conn.execute("SELECT name, type, scope FROM duckdb_secrets()").fetchall()


def test_e5_reads_local_tables_through_views(tmp_path):
    accesses = [
        _local_access(
            tmp_path, "store_sales", {"ss_item_sk": [1, 2, 2], "ss_qty": [5, 6, 7]}
        ),
        _local_access(tmp_path, "item", {"i_item_sk": [1, 2], "i_name": ["a", "b"]}),
    ]
    conn = connect(accesses)

    plain = run_query(conn, "SELECT count(*) FROM store_sales")
    full = run_query(conn, "SELECT count(*) FROM dqr.sf1.store_sales")
    join = run_query(
        conn,
        "SELECT i_name, ss_qty FROM store_sales JOIN item ON ss_item_sk = i_item_sk "
        "ORDER BY ss_qty",
    )

    assert plain.rows == [(3,)]
    assert full.rows == [(3,)]
    assert join.rows == [("a", 5), ("b", 6), ("b", 7)]
    assert plain.ms >= 0 and full.ms >= 0 and join.ms >= 0


def test_e6_one_secret_per_table_scoped_to_its_location():
    locations = [f"{ACCOUNT_ROOT}/store_sales/", f"{ACCOUNT_ROOT}/item/"]
    accesses = [
        TableAccess("dqr.sf1.store_sales", locations[0], "sv=1&sig=aaa"),
        TableAccess("dqr.sf1.item", locations[1], "sv=1&sig=bbb"),
    ]
    conn = duckdb.connect()

    register_secrets(conn, accesses)

    secrets = _secrets(conn)
    assert len(secrets) == 2
    assert {s[1] for s in secrets} == {"azure"}
    assert sorted(s[2] for s in secrets) == sorted([[loc] for loc in locations])


def test_secret_scope_is_the_location_exactly():
    location = f"{ACCOUNT_ROOT}/item"
    conn = duckdb.connect()

    register_secrets(conn, [TableAccess("dqr.sf1.item", location, "sv=1&sig=bbb")])

    assert [s[2] for s in _secrets(conn)] == [[location]]


def test_secret_connection_string_names_the_account():
    # The DuckDB azure extension rejects a fully qualified abfss:// path ("A invalid
    # connection string has been provided") unless the connection string has
    # `AccountName=<account of the path>`. Found in the first real run (E9).
    class Recorder:
        def __init__(self):
            self.statements = []

        def execute(self, sql):
            self.statements.append(sql)

    recorder = Recorder()
    access = TableAccess("dqr.sf1.item", f"{ACCOUNT_ROOT}/item/", "sv=1&sig=bbb")

    register_secrets(recorder, [access])

    (create,) = [s for s in recorder.statements if s.startswith("CREATE SECRET")]
    assert "AccountName=acct;" in create
    assert "SharedAccessSignature=sv=1&sig=bbb" in create


def test_abfss_location_without_token_is_an_error():
    conn = duckdb.connect()

    with pytest.raises(ReaderError, match=r"dqr\.sf1\.item"):
        register_secrets(
            conn, [TableAccess("dqr.sf1.item", f"{ACCOUNT_ROOT}/item/", "")]
        )

    assert _secrets(conn) == []


def test_local_location_gets_no_secret(tmp_path):
    conn = duckdb.connect()

    register_secrets(conn, [_local_access(tmp_path, "item", {"i_item_sk": [1]})])

    assert _secrets(conn) == []


TOKEN = "sv=2024-01-01&sig=a/b+c=&se=2026"


def test_e7_redact_replaces_every_token_and_keeps_the_rest():
    message = f"failed for {TOKEN} then again {TOKEN}: end"

    assert redact(message, [TOKEN]) == "failed for *** then again ***: end"


def test_e7_redact_masks_url_encoded_forms():
    message = (
        f"plain {TOKEN} | {quote(TOKEN, safe='')} | {quote(TOKEN)} | "
        f"{quote_plus(TOKEN)} | done"
    )

    assert redact(message, [TOKEN]) == "plain *** | *** | *** | *** | done"


def test_e7_redact_masks_any_sig_value():
    message = (
        "GET https://acct.blob.core.windows.net/c?sv=1&sig=Zm9v%2Fbar%3D&se=2 failed"
    )

    assert redact(message, []) == (
        "GET https://acct.blob.core.windows.net/c?sv=1&sig=***&se=2 failed"
    )


def test_e7_redact_without_tokens_leaves_other_text_alone():
    assert redact("table not found", [TOKEN]) == "table not found"
