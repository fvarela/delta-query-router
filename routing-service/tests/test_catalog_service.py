"""Tests for catalog_service - Unity Catalog metadata fetching with caching."""

from unittest.mock import MagicMock, patch

import pytest
from catalog_service import (
    CACHE_TTL_SECONDS,
    TableMetadata,
    _fetch_from_catalog,
    _get_from_cache,
    _unknown_metadata,
    _write_to_cache,
    get_table_metadata,
    get_tables_metadata,
)


TABLE_NAME = "my_catalog.my_schema.my_table"

class TestUnknownMetadata:
    """Conservative fallback returns safe defaults."""
    def test_returns_unknown_defaults(self):
        m = _unknown_metadata(TABLE_NAME)
        assert m.full_name == TABLE_NAME
        assert m.table_type == "UNKNOWN"
        assert m.data_source_format == "UNKNOWN"
        assert m.storage_location is None
        assert m.size_bytes is None
        assert m.has_rls is False
        assert m.has_column_masking is False
        assert m.external_engine_read_support is False
        assert m.cached is False


class TestGetFromCache:
    """Cache read via db.fetch_one."""
    @patch("catalog_service.db")
    def test_cache_hit(self, mock_db):
        mock_db.fetch_one.return_value = {
            "table_name": TABLE_NAME,
            "table_type": "MANAGED",
            "data_source_format": "DELTA",
            "storage_location": "s3://bucket/path",
            "size_bytes": 1024,
            "has_rls": False,
            "has_column_masking": False,
            "external_engine_read_support": True,
            "cached_at": "2026-01-01T00:00:00Z",
            "ttl_seconds": 300,
        }
        result = _get_from_cache(TABLE_NAME)
        assert result is not None
        assert result.full_name == TABLE_NAME
        assert result.table_type == "MANAGED"
        assert result.cached is True
        mock_db.fetch_one.assert_called_once()
    @patch("catalog_service.db")
    def test_cache_miss(self, mock_db):
        mock_db.fetch_one.return_value = None
        result = _get_from_cache(TABLE_NAME)
        assert result is None
    @patch("catalog_service.db")
    def test_null_format_becomes_unknown(self, mock_db):
        mock_db.fetch_one.return_value = {
            "table_name": TABLE_NAME,
            "table_type": "MANAGED",
            "data_source_format": None,
            "storage_location": None,
            "size_bytes": None,
            "has_rls": False,
            "has_column_masking": False,
            "external_engine_read_support": False,
            "cached_at": "2026-01-01T00:00:00Z",
            "ttl_seconds": 300,
        }
        result = _get_from_cache(TABLE_NAME)
        assert result.data_source_format == "UNKNOWN"

class TestWriteToCache:
    """Cache write via db.execute (upsert)."""
    @patch("catalog_service.db")
    def test_upsert_called_with_correct_params(self, mock_db):
        metadata = TableMetadata(
            full_name=TABLE_NAME,
            table_type="MANAGED",
            data_source_format="DELTA",
            storage_location="s3://bucket/path",
            size_bytes=2048,
            has_rls=True,
            has_column_masking=False,
            external_engine_read_support=True,
            cached=False,
        )
        _write_to_cache(metadata)
        mock_db.execute.assert_called_once()
        sql, params = mock_db.execute.call_args[0]
        assert "ON CONFLICT" in sql
        assert params[0] == TABLE_NAME
        assert params[1] == "my_catalog"  # catalog parsed from full_name
        assert params[2] == "my_schema"  # schema parsed from full_name
        assert params[3] == "MANAGED"
    @patch("catalog_service.db")
    def test_single_part_name(self, mock_db):
        """Table name with no dots — catalog and schema are None."""
        metadata = TableMetadata(
            full_name="just_a_table",
            table_type="UNKNOWN",
            data_source_format="UNKNOWN",
            storage_location=None,
            size_bytes=None,
            has_rls=False,
            has_column_masking=False,
            external_engine_read_support=False,
            cached=False,
        )
        _write_to_cache(metadata)
        _, params = mock_db.execute.call_args[0]
        assert params[1] == "just_a_table"  # first part is catalog
        assert params[2] is None  # no schema        

def _make_table_info(
    table_type="MANAGED",
    data_source_format="DELTA",
    storage_location="s3://bucket/path",
    row_filter=None,
    columns=None,
    capabilities=None,
    properties=None,
):
    """Build a mock TableInfo object mimicking databricks-sdk."""
    info = MagicMock()
    info.table_type = MagicMock(value=table_type) if table_type else None
    info.data_source_format = (
        MagicMock(value=data_source_format) if data_source_format else None
    )
    info.storage_location = storage_location
    info.row_filter = row_filter
    info.columns = columns
    if capabilities is not None:
        info.securable_kind_manifest = MagicMock(capabilities=capabilities)
    else:
        info.securable_kind_manifest = None
    info.properties = properties
    return info        


class TestFetchFromCatalog:
    """SDK field extraction from TableInfo."""
    def test_basic_managed_table(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info()
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.table_type == "MANAGED"
        assert result.data_source_format == "DELTA"
        assert result.storage_location == "s3://bucket/path"
        assert result.has_rls is False
        assert result.has_column_masking is False
        assert result.external_engine_read_support is False
        assert result.cached is False
        wc.tables.get.assert_called_once_with(
            TABLE_NAME, include_manifest_capabilities=True
        )
    def test_view_detected(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(table_type="VIEW")
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.table_type == "VIEW"
    def test_rls_detected(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            row_filter=MagicMock()  # any non-None value means RLS
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.has_rls is True
    def test_column_masking_detected(self):
        col_with_mask = MagicMock()
        col_with_mask.mask = MagicMock()  # non-None = masked
        col_without_mask = MagicMock()
        col_without_mask.mask = None
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            columns=[col_without_mask, col_with_mask]
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.has_column_masking is True
    def test_no_column_masking(self):
        col = MagicMock()
        col.mask = None
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(columns=[col])
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.has_column_masking is False
    def test_external_engine_read_support(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            capabilities=["HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT"]
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.external_engine_read_support is True
    def test_size_from_properties(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            properties={"spark.sql.statistics.totalSize": "999999"}
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.size_bytes == 999999
    def test_invalid_size_ignored(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            properties={"spark.sql.statistics.totalSize": "not_a_number"}
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.size_bytes is None
    def test_null_enums_become_unknown(self):
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(
            table_type=None, data_source_format=None
        )
        result = _fetch_from_catalog(TABLE_NAME, wc)
        assert result.table_type == "UNKNOWN"
        assert result.data_source_format == "UNKNOWN"
        
class TestGetTableMetadata:
    """Integration of cache + SDK + fallback."""
    @patch("catalog_service.db")
    def test_cache_hit_skips_sdk(self, mock_db):
        mock_db.fetch_one.return_value = {
            "table_name": TABLE_NAME,
            "table_type": "EXTERNAL",
            "data_source_format": "DELTA",
            "storage_location": "s3://bucket/path",
            "size_bytes": 512,
            "has_rls": False,
            "has_column_masking": False,
            "external_engine_read_support": True,
            "cached_at": "2026-01-01T00:00:00Z",
            "ttl_seconds": 300,
        }
        wc = MagicMock()
        result = get_table_metadata(TABLE_NAME, wc)
        assert result.cached is True
        assert result.table_type == "EXTERNAL"
        wc.tables.get.assert_not_called()
    @patch("catalog_service.db")
    def test_cache_miss_fetches_from_sdk(self, mock_db):
        mock_db.fetch_one.return_value = None  # cache miss
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info()
        result = get_table_metadata(TABLE_NAME, wc)
        assert result.cached is False
        assert result.table_type == "MANAGED"
        wc.tables.get.assert_called_once()
        mock_db.execute.assert_called_once()  # cache write
    def test_no_workspace_client_returns_unknown(self):
        result = get_table_metadata(TABLE_NAME, None)
        assert result.table_type == "UNKNOWN"
        assert result.external_engine_read_support is False
    @patch("catalog_service.db")
    def test_sdk_error_returns_unknown(self, mock_db):
        mock_db.fetch_one.return_value = None  # cache miss
        wc = MagicMock()
        wc.tables.get.side_effect = Exception("API error")
        result = get_table_metadata(TABLE_NAME, wc)
        assert result.table_type == "UNKNOWN"
    @patch("catalog_service.db")
    def test_cache_read_failure_falls_back_to_sdk(self, mock_db):
        mock_db.fetch_one.side_effect = Exception("DB down")
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info(table_type="VIEW")
        result = get_table_metadata(TABLE_NAME, wc)
        assert result.table_type == "VIEW"
    @patch("catalog_service.db")
    def test_cache_write_failure_still_returns_metadata(self, mock_db):
        mock_db.fetch_one.return_value = None  # cache miss
        mock_db.execute.side_effect = Exception("DB write failed")
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info()
        result = get_table_metadata(TABLE_NAME, wc)
        assert result.table_type == "MANAGED"  # still returns data
class TestGetTablesMetadata:
    """Batch lookup."""
    @patch("catalog_service.db")
    def test_returns_dict_keyed_by_name(self, mock_db):
        mock_db.fetch_one.return_value = None  # all cache misses
        wc = MagicMock()
        wc.tables.get.return_value = _make_table_info()
        names = ["cat.sch.table_a", "cat.sch.table_b"]
        result = get_tables_metadata(names, wc)
        assert set(result.keys()) == set(names)
        assert all(isinstance(v, TableMetadata) for v in result.values())
    def test_empty_list(self):
        result = get_tables_metadata([], None)
        assert result == {}