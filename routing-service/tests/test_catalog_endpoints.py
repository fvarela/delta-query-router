"""Tests for Unity Catalog browsing endpoints (task 9)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


# Helper: inject a valid token and return auth header
def _auth_header():
    token = "test-token-abc"
    main._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _make_catalog(name):
    c = MagicMock()
    c.name = name
    return c


def _make_schema(name, catalog_name):
    s = MagicMock()
    s.name = name
    s.catalog_name = catalog_name
    return s


def _make_table_info(
    name="my_table",
    full_name="cat.sch.my_table",
    table_type="MANAGED",
    data_source_format="DELTA",
    storage_location="s3://bucket/path",
    row_filter=None,
    columns=None,
    capabilities=None,
    properties=None,
):
    t = MagicMock()
    t.name = name
    t.full_name = full_name
    t.table_type = MagicMock(value=table_type) if table_type else None
    t.data_source_format = (
        MagicMock(value=data_source_format) if data_source_format else None
    )
    t.storage_location = storage_location
    t.row_filter = row_filter
    if columns is not None:
        t.columns = columns
    else:
        col = MagicMock()
        col.name = "id"
        col.type_text = "INT"
        col.type_name = MagicMock(value="INT")
        col.mask = None
        t.columns = [col]
    if capabilities is not None:
        t.securable_kind_manifest = MagicMock(capabilities=capabilities)
    else:
        t.securable_kind_manifest = None
    t.properties = properties
    return t


class TestNoWorkspace:
    """All endpoints return 400 when no Databricks workspace is connected."""

    def setup_method(self):
        main._workspace_client = None

    def test_catalogs_400(self):
        resp = client.get("/api/databricks/catalogs", headers=_auth_header())
        assert resp.status_code == 400
        assert "No Databricks workspace" in resp.json()["detail"]

    def test_schemas_400(self):
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas", headers=_auth_header()
        )
        assert resp.status_code == 400

    def test_tables_400(self):
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas/sch/tables", headers=_auth_header()
        )
        assert resp.status_code == 400


class TestNoAuth:
    """All endpoints return 401 without a valid token."""

    def test_catalogs_401(self):
        resp = client.get("/api/databricks/catalogs")
        assert resp.status_code == 401

    def test_schemas_401(self):
        resp = client.get("/api/databricks/catalogs/cat/schemas")
        assert resp.status_code == 401

    def test_tables_401(self):
        resp = client.get("/api/databricks/catalogs/cat/schemas/sch/tables")
        assert resp.status_code == 401


class TestListCatalogs:
    def setup_method(self):
        self.wc = MagicMock()
        main._workspace_client = self.wc

    def teardown_method(self):
        main._workspace_client = None

    def test_returns_catalog_names(self):
        self.wc.catalogs.list.return_value = [
            _make_catalog("prod"),
            _make_catalog("dev"),
        ]
        resp = client.get("/api/databricks/catalogs", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data == [{"name": "prod"}, {"name": "dev"}]

    def test_empty_list(self):
        self.wc.catalogs.list.return_value = []
        resp = client.get("/api/databricks/catalogs", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_sdk_error_returns_500(self):
        self.wc.catalogs.list.side_effect = Exception("SDK boom")
        resp = client.get("/api/databricks/catalogs", headers=_auth_header())
        assert resp.status_code == 500


class TestListSchemas:
    def setup_method(self):
        self.wc = MagicMock()
        main._workspace_client = self.wc

    def teardown_method(self):
        main._workspace_client = None

    def test_returns_schema_names(self):
        self.wc.schemas.list.return_value = [
            _make_schema("default", "prod"),
            _make_schema("analytics", "prod"),
        ]
        # Mock the raw API call for EXTERNAL_USE_SCHEMA grant check
        self.wc.api_client.do.return_value = {"privilege_assignments": []}
        resp = client.get(
            "/api/databricks/catalogs/prod/schemas", headers=_auth_header()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data == [
            {"name": "default", "catalog_name": "prod", "external_use_schema": False},
            {"name": "analytics", "catalog_name": "prod", "external_use_schema": False},
        ]
        self.wc.schemas.list.assert_called_once_with(catalog_name="prod")


class TestListTables:
    def setup_method(self):
        self.wc = MagicMock()
        main._workspace_client = self.wc

    def teardown_method(self):
        main._workspace_client = None

    @patch("main.catalog_service._write_to_cache")
    def test_returns_table_info(self, mock_cache_write):
        self.wc.tables.list.return_value = [
            _make_table_info(
                properties={
                    "spark.sql.statistics.totalSize": "1024",
                    "spark.sql.statistics.numRows": "100",
                },
            )
        ]
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas/sch/tables", headers=_auth_header()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        table = data[0]
        assert table["name"] == "my_table"
        assert table["full_name"] == "cat.sch.my_table"
        assert table["table_type"] == "MANAGED"
        assert table["data_source_format"] == "DELTA"
        assert table["size_bytes"] == 1024
        assert table["row_count"] == 100
        assert table["columns"] == [{"name": "id", "type_text": "INT"}]

    @patch("main.catalog_service._write_to_cache")
    def test_cache_warming_called(self, mock_cache_write):
        self.wc.tables.list.return_value = [
            _make_table_info(name="t1", full_name="cat.sch.t1"),
            _make_table_info(name="t2", full_name="cat.sch.t2"),
        ]
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas/sch/tables", headers=_auth_header()
        )
        assert resp.status_code == 200
        assert mock_cache_write.call_count == 2

    @patch("main.catalog_service._write_to_cache")
    def test_cache_warming_failure_doesnt_break_response(self, mock_cache_write):
        mock_cache_write.side_effect = Exception("DB down")
        self.wc.tables.list.return_value = [_make_table_info()]
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas/sch/tables", headers=_auth_header()
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @patch("main.catalog_service._write_to_cache")
    def test_external_engine_read_support(self, mock_cache_write):
        self.wc.tables.list.return_value = [
            _make_table_info(capabilities=["HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT"])
        ]
        resp = client.get(
            "/api/databricks/catalogs/cat/schemas/sch/tables", headers=_auth_header()
        )
        table = resp.json()[0]
        assert table["external_engine_read_support"] is True
