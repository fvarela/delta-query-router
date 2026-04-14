"""Tests for foreign/federated table routing — ensures tables without
storage_location or external engine read support always route to Databricks.

Covers edge cases not exercised by the basic system-rule tests in
test_routing_engine.py: mixed queries (foreign + regular tables), specific
federation formats (SQLSERVER, SNOWFLAKE, etc.), null storage_location,
and end-to-end route_query with federated metadata.
"""

from unittest.mock import patch

import pytest

from catalog_service import TableMetadata
from query_analyzer import QueryAnalysis
from routing_engine import (
    EngineStates,
    RoutingSettings,
    _is_duckdb_compatible,
    _match_rule,
    route_query,
)
import routing_engine


# --- Helpers ---


def _analysis(tables=None, complexity_score=0.0):
    tables = tables or []
    return QueryAnalysis(
        statement_type="SELECT",
        tables=tables,
        num_tables=len(tables),
        num_joins=0,
        num_aggregations=0,
        num_subqueries=0,
        has_group_by=False,
        has_order_by=False,
        has_limit=False,
        has_window_functions=False,
        num_columns_selected=1,
        complexity_score=complexity_score,
        error=None,
    )


def _meta(
    full_name="cat.sch.tbl",
    table_type="MANAGED",
    data_source_format="DELTA",
    has_rls=False,
    has_column_masking=False,
    external_engine_read_support=True,
    storage_location="s3://bucket/path",
    size_bytes=1024,
):
    return TableMetadata(
        full_name=full_name,
        table_type=table_type,
        data_source_format=data_source_format,
        storage_location=storage_location,
        size_bytes=size_bytes,
        has_rls=has_rls,
        has_column_masking=has_column_masking,
        external_engine_read_support=external_engine_read_support,
        cached=False,
    )


# System rules matching the seed data
SYSTEM_RULES = [
    {
        "id": 1,
        "priority": 1,
        "condition_type": "table_type",
        "condition_value": "VIEW",
        "target_engine": "databricks",
    },
    {
        "id": 2,
        "priority": 2,
        "condition_type": "has_governance",
        "condition_value": "row_filter",
        "target_engine": "databricks",
    },
    {
        "id": 3,
        "priority": 3,
        "condition_type": "has_governance",
        "condition_value": "column_mask",
        "target_engine": "databricks",
    },
    {
        "id": 4,
        "priority": 4,
        "condition_type": "table_type",
        "condition_value": "FOREIGN",
        "target_engine": "databricks",
    },
    {
        "id": 5,
        "priority": 5,
        "condition_type": "external_access",
        "condition_value": "false",
        "target_engine": "databricks",
    },
]


@pytest.fixture(autouse=True)
def reset_cache():
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


@pytest.fixture
def mock_db():
    with patch("routing_engine.db") as mdb:
        mdb.fetch_all.return_value = SYSTEM_RULES
        yield mdb


# ---------------------------------------------------------------------------
# _is_duckdb_compatible — foreign/federated edge cases
# ---------------------------------------------------------------------------


class TestDuckdbCompatibilityForeign:
    """Tables that cannot be read by DuckDB due to federation constraints."""

    def test_foreign_table_type_not_compatible(self):
        """FOREIGN table type (e.g. Lakehouse Federation) → incompatible."""
        meta = {"t": _meta(table_type="FOREIGN", data_source_format="SQLSERVER")}
        assert _is_duckdb_compatible(meta) is False

    def test_sqlserver_format_not_compatible(self):
        """SQLSERVER data source format → incompatible (not DELTA/PARQUET/UNKNOWN)."""
        meta = {"t": _meta(data_source_format="SQLSERVER")}
        assert _is_duckdb_compatible(meta) is False

    def test_snowflake_format_not_compatible(self):
        meta = {"t": _meta(data_source_format="SNOWFLAKE")}
        assert _is_duckdb_compatible(meta) is False

    def test_mysql_format_not_compatible(self):
        meta = {"t": _meta(data_source_format="MYSQL")}
        assert _is_duckdb_compatible(meta) is False

    def test_postgresql_format_not_compatible(self):
        meta = {"t": _meta(data_source_format="POSTGRESQL")}
        assert _is_duckdb_compatible(meta) is False

    def test_bigquery_format_not_compatible(self):
        meta = {"t": _meta(data_source_format="BIGQUERY")}
        assert _is_duckdb_compatible(meta) is False

    def test_no_storage_location_with_external_support_is_compatible(self):
        """A MANAGED table with no storage_location but with external read support
        is still DuckDB-compatible (storage_location is not checked by _is_duckdb_compatible)."""
        meta = {"t": _meta(storage_location=None, external_engine_read_support=True)}
        assert _is_duckdb_compatible(meta) is True

    def test_no_storage_location_without_external_support_not_compatible(self):
        """No external read support → incompatible regardless of storage_location."""
        meta = {"t": _meta(storage_location=None, external_engine_read_support=False)}
        assert _is_duckdb_compatible(meta) is False

    def test_mixed_tables_one_foreign_makes_all_incompatible(self):
        """If any table in a multi-table query is foreign, the whole query is incompatible."""
        meta = {
            "cat.sch.regular": _meta(full_name="cat.sch.regular"),
            "cat.sch.foreign": _meta(
                full_name="cat.sch.foreign",
                table_type="FOREIGN",
                data_source_format="SQLSERVER",
                external_engine_read_support=False,
            ),
        }
        assert _is_duckdb_compatible(meta) is False

    def test_mixed_tables_one_no_external_access_makes_incompatible(self):
        """One table without external read support makes the whole query incompatible."""
        meta = {
            "t1": _meta(full_name="t1"),
            "t2": _meta(full_name="t2", external_engine_read_support=False),
        }
        assert _is_duckdb_compatible(meta) is False

    def test_multiple_compatible_tables_all_ok(self):
        meta = {
            "t1": _meta(full_name="t1", data_source_format="DELTA"),
            "t2": _meta(full_name="t2", data_source_format="PARQUET"),
        }
        assert _is_duckdb_compatible(meta) is True

    def test_unknown_table_type_with_delta_format_compatible(self):
        """UNKNOWN table type (from _unknown_metadata fallback) with DELTA format
        and external read support → compatible (conservative but functional)."""
        meta = {"t": _meta(table_type="UNKNOWN", data_source_format="DELTA")}
        assert _is_duckdb_compatible(meta) is True

    def test_unknown_format_with_external_support_compatible(self):
        """UNKNOWN format with external read support → compatible
        (UNKNOWN is in the allowed formats list)."""
        meta = {"t": _meta(data_source_format="UNKNOWN")}
        assert _is_duckdb_compatible(meta) is True

    def test_unknown_metadata_fallback_not_compatible(self):
        """The _unknown_metadata fallback (external_engine_read_support=False)
        should make a table incompatible — ensuring cold-cache routes to Databricks."""
        meta = {
            "t": _meta(
                table_type="UNKNOWN",
                data_source_format="UNKNOWN",
                storage_location=None,
                external_engine_read_support=False,
            )
        }
        assert _is_duckdb_compatible(meta) is False


# ---------------------------------------------------------------------------
# _match_rule — foreign/federated-specific rule matching
# ---------------------------------------------------------------------------


class TestMatchRuleForeign:
    """Rule matching for foreign/federated table conditions."""

    def test_table_type_foreign_matches(self):
        rule = {"condition_type": "table_type", "condition_value": "FOREIGN"}
        meta = {"t": _meta(table_type="FOREIGN")}
        assert _match_rule(rule, _analysis(), meta) is True

    def test_table_type_foreign_no_match_on_managed(self):
        rule = {"condition_type": "table_type", "condition_value": "FOREIGN"}
        meta = {"t": _meta(table_type="MANAGED")}
        assert _match_rule(rule, _analysis(), meta) is False

    def test_external_access_false_matches_foreign_table(self):
        """Foreign tables without external read support match the external_access=false rule."""
        rule = {"condition_type": "external_access", "condition_value": "false"}
        meta = {
            "t": _meta(
                table_type="FOREIGN",
                data_source_format="SQLSERVER",
                external_engine_read_support=False,
            )
        }
        assert _match_rule(rule, _analysis(), meta) is True

    def test_external_access_false_no_match_when_supported(self):
        rule = {"condition_type": "external_access", "condition_value": "false"}
        meta = {"t": _meta(external_engine_read_support=True)}
        assert _match_rule(rule, _analysis(), meta) is False

    def test_mixed_tables_foreign_match_any(self):
        """Rule should match if ANY table in the query matches (not all)."""
        rule = {"condition_type": "table_type", "condition_value": "FOREIGN"}
        meta = {
            "cat.sch.regular": _meta(full_name="cat.sch.regular", table_type="MANAGED"),
            "cat.sch.foreign": _meta(full_name="cat.sch.foreign", table_type="FOREIGN"),
        }
        assert _match_rule(rule, _analysis(), meta) is True

    def test_table_name_pattern_matches_foreign_table(self):
        """Table name pattern matching works on foreign tables too."""
        rule = {
            "condition_type": "table_name_pattern",
            "condition_value": "*.federation.*",
        }
        meta = {
            "cat.federation.orders": _meta(
                full_name="cat.federation.orders",
                table_type="FOREIGN",
            )
        }
        assert _match_rule(rule, _analysis(), meta) is True


# ---------------------------------------------------------------------------
# route_query — end-to-end foreign table routing
# ---------------------------------------------------------------------------


class TestRouteQueryForeign:
    """Integration tests: full routing pipeline with foreign/federated tables."""

    def test_foreign_table_hits_system_rule(self, mock_db):
        """A FOREIGN table should be caught by system rule #4."""
        meta = {"cat.sch.f": _meta(full_name="cat.sch.f", table_type="FOREIGN")}
        result = route_query(_analysis(tables=["cat.sch.f"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 4

    def test_foreign_without_external_access_hits_earlier_rule(self, mock_db):
        """A FOREIGN table also lacks external access — but FOREIGN rule (priority 4)
        fires before external_access rule (priority 5)."""
        meta = {
            "t": _meta(
                table_type="FOREIGN",
                data_source_format="SQLSERVER",
                external_engine_read_support=False,
            )
        }
        result = route_query(_analysis(tables=["t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.rule_id == 4  # FOREIGN rule fires first

    def test_no_external_access_managed_table_hits_rule_5(self, mock_db):
        """A MANAGED table without external read support (e.g., cold cache fallback)
        should be caught by rule #5 (external_access=false)."""
        meta = {
            "t": _meta(
                table_type="MANAGED",
                external_engine_read_support=False,
            )
        }
        result = route_query(_analysis(tables=["t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.rule_id == 5

    def test_foreign_overrides_forced_duckdb(self, mock_db):
        """System rules take priority over forced mode — even if user forces duckdb,
        a foreign table must route to Databricks."""
        meta = {"t": _meta(table_type="FOREIGN")}
        result = route_query(_analysis(tables=["t"]), meta, routing_mode="duckdb")
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"

    def test_mixed_query_foreign_plus_regular(self, mock_db):
        """A query touching both a regular and a foreign table should route to
        Databricks because the FOREIGN table triggers the system rule."""
        meta = {
            "cat.sch.regular": _meta(full_name="cat.sch.regular"),
            "cat.sch.foreign": _meta(full_name="cat.sch.foreign", table_type="FOREIGN"),
        }
        result = route_query(
            _analysis(tables=["cat.sch.regular", "cat.sch.foreign"]), meta
        )
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 4

    def test_sqlserver_format_with_no_external_access(self, mock_db):
        """SQLSERVER-format table without external access → rule #5."""
        meta = {
            "t": _meta(
                data_source_format="SQLSERVER",
                external_engine_read_support=False,
            )
        }
        result = route_query(_analysis(tables=["t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.rule_id == 5

    def test_routing_events_contain_foreign_rule_info(self, mock_db):
        """Verify the routing log events contain meaningful info about the matched rule."""
        meta = {"t": _meta(table_type="FOREIGN")}
        result = route_query(_analysis(tables=["t"]), meta)
        rule_events = [e for e in result.events if e.level == "rule"]
        assert len(rule_events) >= 1
        assert "FOREIGN" in rule_events[0].message
        assert "table_type" in rule_events[0].message
