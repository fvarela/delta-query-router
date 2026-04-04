"""Tests for permissions — user and system table access checks (Task 62)."""

from unittest.mock import MagicMock

from databricks.sdk.errors import NotFound, PermissionDenied

import permissions


def _mock_wc(denied_tables: set[str] | None = None):
    """Return a mock WorkspaceClient that denies specific tables."""
    denied = denied_tables or set()
    wc = MagicMock()

    def fake_get(table_name):
        if table_name in denied:
            raise PermissionDenied("Forbidden")
        return MagicMock()  # success

    wc.tables.get.side_effect = fake_get
    return wc


class TestCheckUserTableAccess:
    def test_all_accessible(self):
        wc = _mock_wc(denied_tables=set())
        result = permissions.check_user_table_access(
            ["catalog.schema.t1", "catalog.schema.t2"], wc
        )
        assert result == []

    def test_one_denied(self):
        wc = _mock_wc(denied_tables={"catalog.schema.t2"})
        result = permissions.check_user_table_access(
            ["catalog.schema.t1", "catalog.schema.t2"], wc
        )
        assert result == ["catalog.schema.t2"]

    def test_multiple_denied(self):
        wc = _mock_wc(denied_tables={"catalog.schema.t1", "catalog.schema.t3"})
        result = permissions.check_user_table_access(
            ["catalog.schema.t1", "catalog.schema.t2", "catalog.schema.t3"], wc
        )
        assert result == ["catalog.schema.t1", "catalog.schema.t3"]

    def test_empty_table_list(self):
        wc = _mock_wc()
        result = permissions.check_user_table_access([], wc)
        assert result == []

    def test_not_found_treated_as_denied(self):
        wc = MagicMock()
        wc.tables.get.side_effect = NotFound("Table not found")
        result = permissions.check_user_table_access(["catalog.schema.gone"], wc)
        assert result == ["catalog.schema.gone"]

    def test_network_error_treated_as_denied(self):
        wc = MagicMock()
        wc.tables.get.side_effect = ConnectionError("network down")
        result = permissions.check_user_table_access(["catalog.schema.t1"], wc)
        assert result == ["catalog.schema.t1"]


class TestCheckSystemTableAccess:
    def test_all_accessible(self):
        wc = _mock_wc(denied_tables=set())
        result = permissions.check_system_table_access(["catalog.schema.t1"], wc)
        assert result == []

    def test_denied_returns_table_names(self):
        wc = _mock_wc(denied_tables={"catalog.schema.t1"})
        result = permissions.check_system_table_access(["catalog.schema.t1"], wc)
        assert result == ["catalog.schema.t1"]
