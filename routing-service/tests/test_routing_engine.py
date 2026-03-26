"""Tests for routing_engine — routing decision pipeline (task 5)."""

from unittest.mock import patch

import pytest

from catalog_service import TableMetadata
from query_analyzer import QueryAnalysis
from routing_engine import RoutingDecision, _match_rule, route_query
import routing_engine


# --- Helpers ---


def _analysis(
    statement_type="SELECT",
    tables=None,
    complexity_score=0.0,
    error=None,
):
    """Build a minimal QueryAnalysis for testing."""
    tables = tables or []
    return QueryAnalysis(
        statement_type=statement_type,
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
        error=error,
    )


def _metadata(
    full_name="cat.sch.tbl",
    table_type="MANAGED",
    data_source_format="DELTA",
    has_rls=False,
    has_column_masking=False,
    external_engine_read_support=True,
    storage_location="s3://bucket/path",
    size_bytes=1024,
):
    """Build a TableMetadata for testing."""
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


# System rules matching the seed data in schema.sql
SYSTEM_RULES = [
    {
        "id": 1,
        "priority": 1,
        "condition_type": "table_type",
        "condition_value": "VIEW",
        "target_engine": "databricks",
        "is_system": True,
    },
    {
        "id": 2,
        "priority": 2,
        "condition_type": "has_governance",
        "condition_value": "row_filter",
        "target_engine": "databricks",
        "is_system": True,
    },
    {
        "id": 3,
        "priority": 3,
        "condition_type": "has_governance",
        "condition_value": "column_mask",
        "target_engine": "databricks",
        "is_system": True,
    },
    {
        "id": 4,
        "priority": 4,
        "condition_type": "table_type",
        "condition_value": "FOREIGN",
        "target_engine": "databricks",
        "is_system": True,
    },
    {
        "id": 5,
        "priority": 5,
        "condition_type": "external_access",
        "condition_value": "false",
        "target_engine": "databricks",
        "is_system": True,
    },
]


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the rule cache before every test."""
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


@pytest.fixture
def mock_db():
    """Patch routing_engine.db and pre-load system rules."""
    with patch("routing_engine.db") as mdb:
        mdb.fetch_all.return_value = SYSTEM_RULES
        yield mdb


def _mock_db_with_rules(rules):
    """Return a patch context that loads custom rules."""
    return patch("routing_engine.db", **{"fetch_all.return_value": rules})


# --- Error check ---


class TestErrorCheck:
    """Queries with analysis errors are rejected before routing."""

    def test_parse_error_raises(self, mock_db):
        analysis = _analysis(error="parse error")
        with pytest.raises(ValueError, match="parse error"):
            route_query(analysis, {})

    def test_empty_sql_raises(self, mock_db):
        analysis = _analysis(error="empty SQL")
        with pytest.raises(ValueError, match="empty SQL"):
            route_query(analysis, {})


# --- System rules ---


class TestSystemRules:
    """System hard rules always route to Databricks."""

    def test_view_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.v": _metadata(full_name="cat.sch.v", table_type="VIEW")}
        result = route_query(_analysis(tables=["cat.sch.v"]), meta)
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"
        assert result.rule_id == 1

    def test_rls_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(has_rls=True)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"
        assert result.rule_id == 2

    def test_column_masking_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(has_column_masking=True)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"
        assert result.rule_id == 3

    def test_foreign_table_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.f": _metadata(full_name="cat.sch.f", table_type="FOREIGN")}
        result = route_query(_analysis(tables=["cat.sch.f"]), meta)
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"
        assert result.rule_id == 4

    def test_no_external_access_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(external_engine_read_support=False)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"
        assert result.rule_id == 5

    def test_system_rule_overrides_forced_duckdb(self, mock_db):
        """System rules always win, even when user forces duckdb."""
        meta = {"cat.sch.v": _metadata(full_name="cat.sch.v", table_type="VIEW")}
        result = route_query(
            _analysis(tables=["cat.sch.v"]), meta, routing_mode="duckdb"
        )
        assert result.engine == "databricks"
        assert result.stage == "SYSTEM_RULE"


# --- Forced mode ---


class TestForcedMode:
    """Forced routing mode when no system rules trigger."""

    def test_forced_duckdb(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"]), meta, routing_mode="duckdb"
        )
        assert result.engine == "duckdb"
        assert result.stage == "FORCED"

    def test_forced_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"]), meta, routing_mode="databricks"
        )
        assert result.engine == "databricks"
        assert result.stage == "FORCED"


# --- User rules ---


class TestUserRules:
    """User-defined rules match after system rules and forced mode."""

    def test_complexity_gt_matches(self):
        rules = SYSTEM_RULES + [
            {
                "id": 100,
                "priority": 10,
                "condition_type": "complexity_gt",
                "condition_value": "10",
                "target_engine": "databricks",
                "is_system": False,
            },
        ]
        with _mock_db_with_rules(rules):
            meta = {"cat.sch.t": _metadata()}
            result = route_query(
                _analysis(tables=["cat.sch.t"], complexity_score=15.0), meta
            )
            assert result.engine == "databricks"
            assert result.stage == "USER_RULE"
            assert result.rule_id == 100

    def test_complexity_gt_no_match(self):
        rules = SYSTEM_RULES + [
            {
                "id": 101,
                "priority": 10,
                "condition_type": "complexity_gt",
                "condition_value": "10",
                "target_engine": "databricks",
                "is_system": False,
            },
        ]
        with _mock_db_with_rules(rules):
            meta = {"cat.sch.t": _metadata()}
            result = route_query(
                _analysis(tables=["cat.sch.t"], complexity_score=3.0), meta
            )
            # Should fall through to fallback, not match user rule
            assert result.stage == "FALLBACK"

    def test_table_name_pattern_matches(self):
        rules = SYSTEM_RULES + [
            {
                "id": 102,
                "priority": 10,
                "condition_type": "table_name_pattern",
                "condition_value": "prod.*",
                "target_engine": "databricks",
                "is_system": False,
            },
        ]
        with _mock_db_with_rules(rules):
            meta = {"prod.sales.orders": _metadata(full_name="prod.sales.orders")}
            result = route_query(_analysis(tables=["prod.sales.orders"]), meta)
            assert result.engine == "databricks"
            assert result.stage == "USER_RULE"
            assert result.rule_id == 102

    def test_table_name_pattern_no_match(self):
        rules = SYSTEM_RULES + [
            {
                "id": 102,
                "priority": 10,
                "condition_type": "table_name_pattern",
                "condition_value": "prod.*",
                "target_engine": "databricks",
                "is_system": False,
            },
        ]
        with _mock_db_with_rules(rules):
            meta = {"dev.test.tbl": _metadata(full_name="dev.test.tbl")}
            result = route_query(_analysis(tables=["dev.test.tbl"]), meta)
            assert result.stage == "FALLBACK"


# --- Fallback ---


class TestFallback:
    """Fallback heuristic when no rules match."""

    def test_simple_delta_routes_to_duckdb(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=2.0), meta
        )
        assert result.engine == "duckdb"
        assert result.stage == "FALLBACK"
        assert "DuckDB-compatible" in result.reason

    def test_complex_query_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=10.0), meta
        )
        assert result.engine == "databricks"
        assert result.stage == "FALLBACK"

    def test_iceberg_routes_to_databricks(self, mock_db):
        """Iceberg tables route to Databricks until duckdb-worker has the extension."""
        meta = {"cat.sch.t": _metadata(data_source_format="ICEBERG")}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        assert result.engine == "databricks"
        assert result.stage == "FALLBACK"

    def test_parquet_routes_to_duckdb(self, mock_db):
        meta = {"cat.sch.t": _metadata(data_source_format="PARQUET")}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        assert result.engine == "duckdb"
        assert result.stage == "FALLBACK"

    def test_no_tables_low_complexity_routes_to_duckdb(self, mock_db):
        """SELECT 1 with no table metadata — all() on empty is True."""
        result = route_query(_analysis(complexity_score=0.0), {})
        assert result.engine == "duckdb"
        assert result.stage == "FALLBACK"

    def test_mixed_tables_one_bad_routes_to_databricks(self, mock_db):
        """If any table is not DuckDB-compatible, route to Databricks."""
        meta = {
            "cat.sch.good": _metadata(full_name="cat.sch.good"),
            "cat.sch.bad": _metadata(
                full_name="cat.sch.bad", data_source_format="SQLSERVER"
            ),
        }
        result = route_query(
            _analysis(tables=["cat.sch.good", "cat.sch.bad"], complexity_score=1.0),
            meta,
        )
        assert result.engine == "databricks"
        assert result.stage == "FALLBACK"


# --- Rule matching unit tests ---


class TestMatchRule:
    """Unit tests for _match_rule."""

    def test_unknown_condition_type_returns_false(self):
        rule = {"condition_type": "nonexistent", "condition_value": "whatever"}
        assert _match_rule(rule, _analysis(), {"t": _metadata()}) is False

    def test_complexity_gt_invalid_value(self):
        rule = {"condition_type": "complexity_gt", "condition_value": "not_a_number"}
        assert (
            _match_rule(rule, _analysis(complexity_score=100), {"t": _metadata()})
            is False
        )

    def test_external_access_true_doesnt_match(self):
        """Rule says external_access=false, but table HAS external access — no match."""
        rule = {"condition_type": "external_access", "condition_value": "false"}
        assert (
            _match_rule(
                rule, _analysis(), {"t": _metadata(external_engine_read_support=True)}
            )
            is False
        )


# --- Rule caching ---


class TestRuleCaching:
    """Rule cache refreshes after TTL."""

    def test_cache_reused_within_ttl(self):
        with patch("routing_engine.db") as mock_db:
            mock_db.fetch_all.return_value = SYSTEM_RULES

            meta = {"cat.sch.t": _metadata()}
            analysis = _analysis(tables=["cat.sch.t"], complexity_score=1.0)

            route_query(analysis, meta)
            route_query(analysis, meta)
            # Only one DB call — second query uses cache
            assert mock_db.fetch_all.call_count == 1
