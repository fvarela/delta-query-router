"""Tests for routing_engine — routing decision pipeline (task 5)."""

from unittest.mock import patch

import pytest

from catalog_service import TableMetadata
from query_analyzer import QueryAnalysis
from routing_engine import (
    EngineStates,
    RoutingDecision,
    RoutingResult,
    RoutingSettings,
    _is_duckdb_compatible,
    _match_rule,
    _score_engines,
    route_query,
)
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
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 1

    def test_rls_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(has_rls=True)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 2

    def test_column_masking_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(has_column_masking=True)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 3

    def test_foreign_table_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.f": _metadata(full_name="cat.sch.f", table_type="FOREIGN")}
        result = route_query(_analysis(tables=["cat.sch.f"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 4

    def test_no_external_access_routes_to_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata(external_engine_read_support=False)}
        result = route_query(_analysis(tables=["cat.sch.t"]), meta)
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"
        assert result.decision.rule_id == 5

    def test_system_rule_overrides_forced_duckdb(self, mock_db):
        """System rules always win, even when user forces duckdb."""
        meta = {"cat.sch.v": _metadata(full_name="cat.sch.v", table_type="VIEW")}
        result = route_query(
            _analysis(tables=["cat.sch.v"]), meta, routing_mode="duckdb"
        )
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "SYSTEM_RULE"


# --- Forced mode ---


class TestForcedMode:
    """Forced routing mode when no system rules trigger."""

    def test_forced_duckdb(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"]), meta, routing_mode="duckdb"
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "FORCED"

    def test_forced_databricks(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"]), meta, routing_mode="databricks"
        )
        assert result.decision.engine == "databricks"
        assert result.decision.stage == "FORCED"


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
            assert result.decision.engine == "databricks"
            assert result.decision.stage == "USER_RULE"
            assert result.decision.rule_id == 100

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
            # Should fall through to scoring, not match user rule
            assert result.decision.stage == "SCORING"

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
            assert result.decision.engine == "databricks"
            assert result.decision.stage == "USER_RULE"
            assert result.decision.rule_id == 102

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
            assert result.decision.stage == "SCORING"


# --- Scoring ---


class TestScoring:
    """Scoring heuristic when no rules match — replaces old fallback."""

    def test_simple_delta_fast_priority_routes_to_duckdb(self, mock_db):
        """Low complexity + fit priority → DuckDB wins."""
        meta = {"cat.sch.t": _metadata()}
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        states = EngineStates(duckdb_running=True, databricks_running=True)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=0.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "SCORING"

    def test_simple_delta_cost_priority_routes_to_duckdb(self, mock_db):
        """Low complexity + cost priority → DuckDB wins (cheaper, no per-query cost)."""
        meta = {"cat.sch.t": _metadata()}
        settings = RoutingSettings(fit_weight=0.2, cost_weight=0.8)
        states = EngineStates(duckdb_running=True, databricks_running=True)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=0.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "SCORING"

    def test_iceberg_routes_to_databricks(self, mock_db):
        """Iceberg tables are not DuckDB-compatible → Databricks always."""
        meta = {"cat.sch.t": _metadata(data_source_format="ICEBERG")}
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        states = EngineStates(duckdb_running=True, databricks_running=True)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        assert result.decision.engine == "databricks"

    def test_parquet_fast_priority_routes_to_duckdb(self, mock_db):
        """Parquet is DuckDB-compatible; fit priority → DuckDB."""
        meta = {"cat.sch.t": _metadata(data_source_format="PARQUET")}
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        states = EngineStates(duckdb_running=True, databricks_running=False)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "SCORING"

    def test_no_tables_low_complexity_routes_to_duckdb(self, mock_db):
        """SELECT 1 with no table metadata — all() on empty is True."""
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        result = route_query(
            _analysis(complexity_score=0.0),
            {},
            settings=settings,
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "SCORING"

    def test_mixed_tables_one_bad_routes_to_databricks(self, mock_db):
        """If any table is not DuckDB-compatible, DuckDB scores 0."""
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
        assert result.decision.engine == "databricks"

    def test_running_bonus_tips_close_decision(self, mock_db):
        """Running bonus can tip the balance when scores are close."""
        meta = {"cat.sch.t": _metadata()}
        # At complexity=5 with balanced weights:
        #   DuckDB:     0.5*0.6 + 0.5*0.7 = 0.65
        #   Databricks: 0.5*0.7125 + 0.5*0.2 + 0.2 bonus = 0.656
        # Bonus tips Databricks slightly ahead
        settings = RoutingSettings(
            fit_weight=0.5,
            cost_weight=0.5,
            running_bonus_duckdb=0.0,
            running_bonus_databricks=0.2,
        )
        states = EngineStates(duckdb_running=True, databricks_running=True)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=5.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        # Databricks gets +0.2 bonus, DuckDB gets +0.0 → Databricks should win
        assert result.decision.engine == "databricks"

    def test_running_bonus_not_applied_when_stopped(self, mock_db):
        """Running bonus is not applied to a stopped engine."""
        meta = {"cat.sch.t": _metadata()}
        settings = RoutingSettings(
            fit_weight=0.8,
            cost_weight=0.2,
            running_bonus_duckdb=0.1,
            running_bonus_databricks=0.5,
        )
        states = EngineStates(duckdb_running=True, databricks_running=False)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=0.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        # DuckDB gets bonus, Databricks doesn't → DuckDB wins
        assert result.decision.engine == "duckdb"

    def test_default_settings_balanced_query_routes_to_duckdb(self, mock_db):
        """With default balanced settings (50/50) and low complexity, DuckDB cost advantage wins."""
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=2.0), meta
        )
        assert result.decision.engine == "duckdb"
        assert result.decision.stage == "SCORING"

    def test_scoring_events_in_log(self, mock_db):
        """Scoring stage emits detailed log events."""
        meta = {"cat.sch.t": _metadata()}
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        states = EngineStates(duckdb_running=True, databricks_running=True)
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=0.0),
            meta,
            settings=settings,
            engine_states=states,
        )
        scoring_events = [e for e in result.events if e.stage == "scoring"]
        assert (
            len(scoring_events) >= 4
        )  # weights, compatible, duckdb line, databricks line, winner
        # Check weights are logged
        weights_event = [e for e in scoring_events if "Weights:" in e.message]
        assert len(weights_event) == 1
        assert "80%" in weights_event[0].message
        # Check winner is logged
        winner_event = [e for e in scoring_events if "Winner:" in e.message]
        assert len(winner_event) == 1


class TestScoreEngines:
    """Unit tests for _score_engines (pure scoring function)."""

    def test_duckdb_incompatible_scores_zero(self):
        """DuckDB gets 0 for incompatible tables."""
        meta = {"t": _metadata(data_source_format="SQLSERVER")}
        settings = RoutingSettings(fit_weight=0.8, cost_weight=0.2)
        states = EngineStates(duckdb_running=True, databricks_running=True)
        events = []
        scores = _score_engines(0.0, meta, settings, states, events)
        assert scores["duckdb"] == 0.0
        assert scores["databricks"] > 0.0

    def test_higher_complexity_increases_databricks_fit_score(self):
        """As complexity increases, Databricks fit score rises."""
        meta = {"t": _metadata()}
        settings = RoutingSettings(fit_weight=1.0, cost_weight=0.0)
        states = EngineStates()
        events_low = []
        events_high = []
        scores_low = _score_engines(0.0, meta, settings, states, events_low)
        scores_high = _score_engines(10.0, meta, settings, states, events_high)
        assert scores_high["databricks"] > scores_low["databricks"]

    def test_higher_complexity_decreases_duckdb_fit_score(self):
        """As complexity increases, DuckDB fit score drops."""
        meta = {"t": _metadata()}
        settings = RoutingSettings(fit_weight=1.0, cost_weight=0.0)
        states = EngineStates()
        events_low = []
        events_high = []
        scores_low = _score_engines(0.0, meta, settings, states, events_low)
        scores_high = _score_engines(10.0, meta, settings, states, events_high)
        assert scores_high["duckdb"] < scores_low["duckdb"]

    def test_cost_only_favors_duckdb(self):
        """With cost_weight=1.0, DuckDB always wins (no per-query cost)."""
        meta = {"t": _metadata()}
        settings = RoutingSettings(fit_weight=0.0, cost_weight=1.0)
        states = EngineStates()
        events = []
        scores = _score_engines(0.0, meta, settings, states, events)
        assert scores["duckdb"] > scores["databricks"]

    def test_fit_only_simple_favors_duckdb(self):
        """With fit_weight=1.0 and low complexity, DuckDB wins."""
        meta = {"t": _metadata()}
        settings = RoutingSettings(fit_weight=1.0, cost_weight=0.0)
        states = EngineStates()
        events = []
        scores = _score_engines(0.0, meta, settings, states, events)
        assert scores["duckdb"] > scores["databricks"]

    def test_running_bonus_applied_only_when_running(self):
        """Running bonus only applies to engines that are running."""
        meta = {"t": _metadata()}
        settings = RoutingSettings(
            fit_weight=0.5,
            cost_weight=0.5,
            running_bonus_duckdb=0.1,
            running_bonus_databricks=0.15,
        )
        events_running = []
        events_stopped = []
        scores_running = _score_engines(
            0.0,
            meta,
            settings,
            EngineStates(duckdb_running=True, databricks_running=True),
            events_running,
        )
        scores_stopped = _score_engines(
            0.0,
            meta,
            settings,
            EngineStates(duckdb_running=False, databricks_running=False),
            events_stopped,
        )
        assert scores_running["duckdb"] == scores_stopped["duckdb"] + 0.1
        assert scores_running["databricks"] == scores_stopped["databricks"] + 0.15


class TestIsDuckdbCompatible:
    """Unit tests for _is_duckdb_compatible helper."""

    def test_delta_is_compatible(self):
        meta = {"t": _metadata(data_source_format="DELTA")}
        assert _is_duckdb_compatible(meta) is True

    def test_parquet_is_compatible(self):
        meta = {"t": _metadata(data_source_format="PARQUET")}
        assert _is_duckdb_compatible(meta) is True

    def test_iceberg_is_not_compatible(self):
        meta = {"t": _metadata(data_source_format="ICEBERG")}
        assert _is_duckdb_compatible(meta) is False

    def test_no_external_access_is_not_compatible(self):
        meta = {"t": _metadata(external_engine_read_support=False)}
        assert _is_duckdb_compatible(meta) is False

    def test_view_is_not_compatible(self):
        meta = {"t": _metadata(table_type="VIEW")}
        assert _is_duckdb_compatible(meta) is False

    def test_empty_metadata_is_compatible(self):
        """No tables = all() on empty → True."""
        assert _is_duckdb_compatible({}) is True


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


# --- Routing log events ---


class TestRoutingLogEvents:
    """Verify route_query() returns structured log events."""

    def test_result_has_events_list(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        assert isinstance(result.events, list)
        assert len(result.events) > 0

    def test_events_have_correct_fields(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        for event in result.events:
            assert hasattr(event, "timestamp")
            assert hasattr(event, "level")
            assert hasattr(event, "stage")
            assert hasattr(event, "message")

    def test_parse_stage_events_present(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        parse_events = [e for e in result.events if e.stage == "parse"]
        assert len(parse_events) >= 3  # statement type, tables, complexity

    def test_rules_stage_events_present(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        rules_events = [e for e in result.events if e.stage == "rules"]
        assert len(rules_events) > 0

    def test_decision_event_present(self, mock_db):
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        decision_events = [e for e in result.events if e.level == "decision"]
        assert len(decision_events) == 1
        assert "Selected engine" in decision_events[0].message

    def test_system_rule_match_logged(self, mock_db):
        meta = {"cat.sch.v": _metadata(full_name="cat.sch.v", table_type="VIEW")}
        result = route_query(_analysis(tables=["cat.sch.v"]), meta)
        rule_events = [e for e in result.events if e.level == "rule"]
        assert len(rule_events) == 1
        assert "System rule matched" in rule_events[0].message

    def test_ml_model_stub_events(self, mock_db):
        """ML model stub emits info + warn events."""
        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        ml_events = [e for e in result.events if e.stage == "ml_model"]
        assert len(ml_events) == 2
        assert ml_events[0].level == "info"
        assert ml_events[1].level == "warn"

    def test_timestamp_format(self, mock_db):
        """Timestamps follow HH:MM:SS.mmm pattern."""
        import re

        meta = {"cat.sch.t": _metadata()}
        result = route_query(
            _analysis(tables=["cat.sch.t"], complexity_score=1.0), meta
        )
        pattern = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")
        for event in result.events:
            assert pattern.match(event.timestamp), f"Bad timestamp: {event.timestamp}"
