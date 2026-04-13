"""Tests for credential_vending module.

Tests the pure functions (URL conversion, SQL rewriting) and the data
structures. Network-dependent functions (API calls, Delta table loading)
are not tested here — they require a live Databricks workspace.
"""

import pytest

# Add parent dir to path so we can import the module
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from credential_vending import (
    CredentialVendingError,
    ResolvedTable,
    TableCredentials,
    _abfss_to_https,
)
from main import _build_read_parquet_expr, _rewrite_sql


# ---------------------------------------------------------------------------
# _abfss_to_https
# ---------------------------------------------------------------------------


class TestAbfssToHttps:
    def test_standard_abfss_url(self):
        uri = "abfss://mycontainer@myaccount.dfs.core.windows.net/path/to/table"
        result = _abfss_to_https(uri, "sv=2020&sig=abc123")
        assert result == (
            "https://myaccount.dfs.core.windows.net/mycontainer/path/to/table"
            "?sv=2020&sig=abc123"
        )

    def test_nested_path(self):
        uri = (
            "abfss://uc-metastore-westus2@stunitycatalogwestus2001"
            ".dfs.core.windows.net/42f033c8/tables/de88c63f/part-00000.parquet"
        )
        result = _abfss_to_https(uri, "sas=token")
        assert "stunitycatalogwestus2001.dfs.core.windows.net" in result
        assert "/uc-metastore-westus2/" in result
        assert "part-00000.parquet" in result
        assert result.endswith("?sas=token")

    def test_empty_sas_token(self):
        uri = "abfss://c@a.dfs.core.windows.net/p"
        result = _abfss_to_https(uri, "")
        assert result == "https://a.dfs.core.windows.net/c/p?"

    def test_invalid_uri_raises(self):
        with pytest.raises(ValueError, match="Cannot parse ABFSS URI"):
            _abfss_to_https("https://not-an-abfss-url.com/path", "token")

    def test_s3_uri_raises(self):
        with pytest.raises(ValueError, match="Cannot parse ABFSS URI"):
            _abfss_to_https("s3://bucket/key", "token")

    def test_url_encoded_sas_token(self):
        """SAS tokens contain URL-encoded characters like %3A — they should
        be passed through unchanged."""
        uri = "abfss://c@a.dfs.core.windows.net/p"
        sas = "st=2026-03-29T16%3A36%3A49Z&sv=2020-02-10&sig=abc%2Fdef"
        result = _abfss_to_https(uri, sas)
        assert result.endswith(f"?{sas}")


# ---------------------------------------------------------------------------
# _build_read_parquet_expr
# ---------------------------------------------------------------------------


class TestBuildReadParquetExpr:
    def test_single_file(self):
        urls = ["https://account.dfs.core.windows.net/c/p/file.parquet?sas=x"]
        expr = _build_read_parquet_expr(urls)
        assert expr.startswith("read_parquet('https://")
        assert "sas=x" in expr
        assert "[" not in expr  # single file, no list syntax
        assert "union_by_name=true" in expr

    def test_multiple_files(self):
        urls = [
            "https://a.dfs.core.windows.net/c/p/file1.parquet?sas=x",
            "https://a.dfs.core.windows.net/c/p/file2.parquet?sas=x",
        ]
        expr = _build_read_parquet_expr(urls)
        assert expr.startswith("read_parquet([")
        assert "file1.parquet" in expr
        assert "file2.parquet" in expr
        assert "union_by_name=true" in expr

    def test_single_quote_in_url_escaped(self):
        urls = ["https://host/path/it's.parquet?sas=x"]
        expr = _build_read_parquet_expr(urls)
        assert "''" in expr  # escaped single quote


# ---------------------------------------------------------------------------
# _rewrite_sql
# ---------------------------------------------------------------------------


class TestRewriteSql:
    def _make_resolved(self, full_name: str, n_files: int = 1) -> ResolvedTable:
        return ResolvedTable(
            full_name=full_name,
            file_urls=[
                f"https://host/c/path/file{i}.parquet?sas=token" for i in range(n_files)
            ],
        )

    def test_simple_replacement(self):
        resolved = {"cat.sch.tbl": self._make_resolved("cat.sch.tbl")}
        sql = "SELECT * FROM cat.sch.tbl LIMIT 10"
        result = _rewrite_sql(sql, resolved)
        assert "cat.sch.tbl" not in result
        assert "read_parquet(" in result

    def test_case_insensitive(self):
        resolved = {"cat.sch.tbl": self._make_resolved("cat.sch.tbl")}
        sql = "SELECT * FROM Cat.Sch.TBL LIMIT 10"
        result = _rewrite_sql(sql, resolved)
        assert "read_parquet(" in result
        assert "Cat.Sch.TBL" not in result

    def test_multiple_tables(self):
        resolved = {
            "cat.sch.t1": self._make_resolved("cat.sch.t1"),
            "cat.sch.t2": self._make_resolved("cat.sch.t2"),
        }
        sql = "SELECT a.x, b.y FROM cat.sch.t1 a JOIN cat.sch.t2 b ON a.id = b.id"
        result = _rewrite_sql(sql, resolved)
        assert "cat.sch.t1" not in result
        assert "cat.sch.t2" not in result
        assert result.count("read_parquet(") == 2

    def test_no_replacement_when_no_tables(self):
        sql = "SELECT 1 + 1"
        result = _rewrite_sql(sql, {})
        assert result == sql

    def test_preserves_rest_of_sql(self):
        resolved = {"c.s.t": self._make_resolved("c.s.t")}
        sql = "SELECT col1, col2 FROM c.s.t WHERE col1 > 5 ORDER BY col2"
        result = _rewrite_sql(sql, resolved)
        assert "WHERE col1 > 5" in result
        assert "ORDER BY col2" in result

    def test_multiple_files_produces_list(self):
        resolved = {"c.s.t": self._make_resolved("c.s.t", n_files=3)}
        sql = "SELECT * FROM c.s.t"
        result = _rewrite_sql(sql, resolved)
        assert "read_parquet([" in result

    def test_longer_name_replaced_first(self):
        """If 'a.b.cd' and 'a.b.c' both exist, the longer one should be
        replaced first to avoid partial matches."""
        resolved = {
            "a.b.c": self._make_resolved("a.b.c"),
            "a.b.cd": self._make_resolved("a.b.cd"),
        }
        sql = "SELECT * FROM a.b.cd JOIN a.b.c ON 1=1"
        result = _rewrite_sql(sql, resolved)
        # Both should be replaced
        assert "a.b.cd" not in result
        assert "a.b.c" not in result
        assert result.count("read_parquet(") == 2

    def test_adds_alias_when_no_alias(self):
        """Table with no alias gets AS <short_name> for column ref support."""
        resolved = {"cat.sch.date_dim": self._make_resolved("cat.sch.date_dim")}
        sql = (
            "SELECT date_dim.d_year FROM cat.sch.date_dim WHERE date_dim.d_year = 2000"
        )
        result = _rewrite_sql(sql, resolved)
        assert "AS date_dim" in result
        assert "date_dim.d_year" in result

    def test_preserves_explicit_as_alias(self):
        """Explicit AS alias is preserved, no extra alias added."""
        resolved = {"cat.sch.date_dim": self._make_resolved("cat.sch.date_dim")}
        sql = "SELECT dt.d_year FROM cat.sch.date_dim AS dt WHERE dt.d_year = 2000"
        result = _rewrite_sql(sql, resolved)
        assert "AS dt" in result
        assert "AS date_dim" not in result

    def test_bare_alias_not_doubled(self):
        """Bare alias (no AS keyword) should not trigger an extra AS alias."""
        resolved = {"cat.sch.t1": self._make_resolved("cat.sch.t1")}
        sql = "SELECT a.x FROM cat.sch.t1 a WHERE a.x > 1"
        result = _rewrite_sql(sql, resolved)
        assert "AS t1" not in result  # bare alias 'a' present, no extra alias
        assert "read_parquet(" in result

    def test_full_qualified_column_ref(self):
        """catalog.schema.table.column becomes alias.column."""
        resolved = {"cat.sch.tbl": self._make_resolved("cat.sch.tbl")}
        sql = "SELECT cat.sch.tbl.col1 FROM cat.sch.tbl"
        result = _rewrite_sql(sql, resolved)
        assert "tbl.col1" in result
        assert "cat.sch.tbl" not in result


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestCredentialVendingError:
    def test_message_includes_table_name(self):
        err = CredentialVendingError("my.table", "something went wrong")
        assert "my.table" in str(err)
        assert "something went wrong" in str(err)

    def test_table_name_attribute(self):
        err = CredentialVendingError("my.table", "msg")
        assert err.table_name == "my.table"


class TestTableCredentials:
    def test_azure_credentials(self):
        tc = TableCredentials(
            table_id="abc123",
            storage_location="abfss://c@a.dfs.core.windows.net/p",
            sas_token="sv=2020&sig=xyz",
        )
        assert tc.sas_token == "sv=2020&sig=xyz"
        assert tc.aws_temp_credentials is None

    def test_aws_credentials(self):
        tc = TableCredentials(
            table_id="abc123",
            storage_location="s3://bucket/key",
            aws_temp_credentials={
                "access_key_id": "AKIA...",
                "secret_access_key": "secret",
                "session_token": "session",
            },
        )
        assert tc.sas_token is None
        assert tc.aws_temp_credentials["access_key_id"] == "AKIA..."


class TestResolvedTable:
    def test_defaults(self):
        rt = ResolvedTable(full_name="c.s.t")
        assert rt.file_urls == []
        assert rt.schema_json == ""
        assert rt.has_deletion_vectors is False

    def test_with_files(self):
        rt = ResolvedTable(
            full_name="c.s.t",
            file_urls=["https://host/file1.parquet", "https://host/file2.parquet"],
            has_deletion_vectors=True,
        )
        assert len(rt.file_urls) == 2
        assert rt.has_deletion_vectors is True
