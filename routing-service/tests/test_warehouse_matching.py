"""Tests for warehouse-to-engine matching logic in main.py."""

from unittest.mock import MagicMock

import main


class TestMatchWarehouseToEngine:
    """_match_warehouse_to_engine — cluster size to engine ID mapping."""

    def _make_warehouse(self, cluster_size=None, warehouse_type="PRO"):
        wh = MagicMock()
        wh.cluster_size = cluster_size
        wh_type = MagicMock()
        wh_type.value = warehouse_type
        wh.warehouse_type = wh_type if warehouse_type else None
        return wh

    def test_2xsmall_serverless(self):
        wh = self._make_warehouse(cluster_size="2X-Small", warehouse_type="PRO")
        assert main._match_warehouse_to_engine(wh) == "databricks-serverless-2xs"

    def test_xsmall_serverless(self):
        wh = self._make_warehouse(cluster_size="X-Small", warehouse_type="PRO")
        assert main._match_warehouse_to_engine(wh) == "databricks-serverless-xs"

    def test_small_serverless(self):
        wh = self._make_warehouse(cluster_size="Small", warehouse_type="PRO")
        assert main._match_warehouse_to_engine(wh) == "databricks-serverless-s"

    def test_unrecognized_size_returns_none(self):
        wh = self._make_warehouse(cluster_size="4X-Large", warehouse_type="PRO")
        assert main._match_warehouse_to_engine(wh) is None

    def test_non_serverless_returns_none(self):
        """Classic (non-PRO) warehouses don't match predefined engines."""
        wh = self._make_warehouse(cluster_size="Small", warehouse_type="CLASSIC")
        assert main._match_warehouse_to_engine(wh) is None

    def test_no_warehouse_type_returns_none(self):
        wh = self._make_warehouse(cluster_size="Small", warehouse_type=None)
        assert main._match_warehouse_to_engine(wh) is None

    def test_no_cluster_size_returns_none(self):
        wh = self._make_warehouse(cluster_size=None, warehouse_type="PRO")
        assert main._match_warehouse_to_engine(wh) is None
