"""Tests for POST /api/query — query execution endpoint (task 6)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
import auth
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-query"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _mock_routing_rules_empty(*_args, **_kwargs):
    """Return no routing rules — skips system/user rule stages."""
    return []


@pytest.fixture(autouse=True)
def _clear_rule_cache():
    """Reset routing engine rule cache between tests."""
    import routing_engine

    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0
    yield
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


# Default routing settings row returned by db.fetch_one for the scoring stage
_MOCK_SETTINGS_ROW = {
    "fit_weight": 0.5,
    "cost_weight": 0.5,
    "running_bonus_duckdb": 0.2,
    "running_bonus_databricks": 0.1,
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_no_token_returns_401(self):
        resp = client.post("/api/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 401

    def test_bad_token_returns_401(self):
        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1"},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------


class TestSqlValidation:
    def test_empty_sql_returns_400(self):
        resp = client.post("/api/query", json={"sql": ""}, headers=_auth_header())
        assert resp.status_code == 400
        assert "empty SQL" in resp.json()["detail"]

    def test_invalid_sql_returns_400(self):
        resp = client.post(
            "/api/query", json={"sql": "NOT VALID SQL !@#$"}, headers=_auth_header()
        )
        assert resp.status_code == 400

    def test_insert_rejected(self):
        resp = client.post(
            "/api/query",
            json={"sql": "INSERT INTO t VALUES (1)"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "SELECT" in resp.json()["detail"]

    def test_create_rejected(self):
        resp = client.post(
            "/api/query",
            json={"sql": "CREATE TABLE t (id INT)"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "SELECT" in resp.json()["detail"]

    def test_drop_rejected(self):
        resp = client.post(
            "/api/query",
            json={"sql": "DROP TABLE t"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DuckDB execution path
# ---------------------------------------------------------------------------


class TestDuckDbExecution:
    """Test queries routed to the DuckDB worker."""

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_simple_select_via_duckdb(self, mock_client_cls, _rules, _meta, _db):
        """SELECT 1 with no tables → scoring picks DuckDB (low complexity)."""
        # Mock httpx.AsyncClient as async context manager — handles both
        # the engine-state probe and the actual DuckDB execution.
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 200
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.json.return_value = {
            "columns": ["1"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 0.5,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1", "routing_mode": "smart"},
            headers=_auth_header(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation_id"]  # UUID present
        assert data["routing_decision"]["engine"] == "duckdb"
        assert data["routing_decision"]["engine_display_name"] == "DuckDB"
        assert data["routing_decision"]["stage"] == "SCORING"
        assert isinstance(data["routing_decision"]["complexity_score"], (int, float))
        assert data["columns"] == ["1"]
        assert data["rows"] == [[1]]
        assert data["execution"]["execution_time_ms"] == 0.5

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_forced_duckdb(self, mock_client_cls, _rules, _meta, _db):
        """routing_mode=duckdb → FORCED stage."""
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 200
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.json.return_value = {
            "columns": ["x"],
            "rows": [[42]],
            "row_count": 1,
            "execution_time_ms": 1.0,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 42 AS x", "routing_mode": "duckdb"},
            headers=_auth_header(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "duckdb"
        assert data["routing_decision"]["stage"] == "FORCED"

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_duckdb_worker_error_returns_502(self, mock_client_cls, _rules, _meta, _db):
        """DuckDB worker returning 400 → 502 to the caller."""
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 400
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.text = "bad query"
        mock_exec_resp.json.return_value = {"detail": "Parser Error: syntax error"}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1", "routing_mode": "duckdb"},
            headers=_auth_header(),
        )

        assert resp.status_code == 502
        assert "DuckDB worker error" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Databricks execution path
# ---------------------------------------------------------------------------


class TestDatabricksExecution:
    """Test queries routed to Databricks."""

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_forced_databricks_success(self, mock_client_cls, _rules, _meta, _db):
        """routing_mode=databricks with a mocked SDK response."""
        from databricks.sdk.service.sql import StatementState

        # httpx mock for engine probing (scoring stage)
        mock_probe = AsyncMock()
        mock_probe.get.side_effect = Exception("connection refused")
        mock_probe.__aenter__ = AsyncMock(return_value=mock_probe)
        mock_probe.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_probe

        mock_status = MagicMock()
        mock_status.state = StatementState.SUCCEEDED
        mock_status.error = None

        mock_col = MagicMock()
        mock_col.name = "answer"

        mock_schema = MagicMock()
        mock_schema.columns = [mock_col]

        mock_manifest = MagicMock()
        mock_manifest.schema = mock_schema
        mock_manifest.total_row_count = 1

        mock_result = MagicMock()
        mock_result.data_array = [["42"]]

        mock_response = MagicMock()
        mock_response.status = mock_status
        mock_response.manifest = mock_manifest
        mock_response.result = mock_result

        mock_wc = MagicMock()
        mock_wc.statement_execution.execute_statement.return_value = mock_response

        original_wc = main._workspace_client
        original_wid = main._warehouse_id
        try:
            main._workspace_client = mock_wc
            main._warehouse_id = "test-warehouse-id"

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 42 AS answer", "routing_mode": "databricks"},
                headers=_auth_header(),
            )
        finally:
            main._workspace_client = original_wc
            main._warehouse_id = original_wid

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "databricks"
        assert data["routing_decision"]["engine_display_name"] == "Databricks"
        assert data["routing_decision"]["stage"] == "FORCED"
        assert data["columns"] == ["answer"]
        assert data["rows"] == [["42"]]

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_databricks_no_workspace_returns_400(
        self, mock_client_cls, _rules, _meta, _db
    ):
        """Databricks route with no workspace connected → 400."""
        mock_probe = AsyncMock()
        mock_probe.get.side_effect = Exception("connection refused")
        mock_probe.__aenter__ = AsyncMock(return_value=mock_probe)
        mock_probe.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_probe

        original_wc = main._workspace_client
        try:
            main._workspace_client = None

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "routing_mode": "databricks"},
                headers=_auth_header(),
            )
        finally:
            main._workspace_client = original_wc

        assert resp.status_code == 400
        assert "No Databricks workspace" in resp.json()["detail"]

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_databricks_no_warehouse_returns_400(
        self, mock_client_cls, _rules, _meta, _db
    ):
        """Databricks route with workspace but no warehouse → 400."""
        mock_probe = AsyncMock()
        mock_probe.get.side_effect = Exception("connection refused")
        mock_probe.__aenter__ = AsyncMock(return_value=mock_probe)
        mock_probe.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_probe

        original_wc = main._workspace_client
        original_wid = main._warehouse_id
        try:
            main._workspace_client = MagicMock()
            main._warehouse_id = None

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "routing_mode": "databricks"},
                headers=_auth_header(),
            )
        finally:
            main._workspace_client = original_wc
            main._warehouse_id = original_wid

        assert resp.status_code == 400
        assert "No SQL warehouse" in resp.json()["detail"]

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_databricks_failed_execution_returns_502(
        self, mock_client_cls, _rules, _meta, _db
    ):
        """Databricks FAILED state → 502."""
        from databricks.sdk.service.sql import StatementState

        mock_probe = AsyncMock()
        mock_probe.get.side_effect = Exception("connection refused")
        mock_probe.__aenter__ = AsyncMock(return_value=mock_probe)
        mock_probe.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_probe

        mock_error = MagicMock()
        mock_error.message = "TABLE_NOT_FOUND"

        mock_status = MagicMock()
        mock_status.state = StatementState.FAILED
        mock_status.error = mock_error

        mock_response = MagicMock()
        mock_response.status = mock_status

        mock_wc = MagicMock()
        mock_wc.statement_execution.execute_statement.return_value = mock_response

        original_wc = main._workspace_client
        original_wid = main._warehouse_id
        try:
            main._workspace_client = mock_wc
            main._warehouse_id = "test-warehouse-id"

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT * FROM nonexistent", "routing_mode": "databricks"},
                headers=_auth_header(),
            )
        finally:
            main._workspace_client = original_wc
            main._warehouse_id = original_wid

        assert resp.status_code == 502
        assert "TABLE_NOT_FOUND" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


class TestResponseStructure:
    """Verify the response matches the frontend QueryExecutionResult shape."""

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_response_has_all_fields(self, mock_client_cls, _rules, _meta, _db):
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 200
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.json.return_value = {
            "columns": ["a", "b"],
            "rows": [[1, 2], [3, 4]],
            "row_count": 2,
            "execution_time_ms": 3.14,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1 AS a, 2 AS b"},
            headers=_auth_header(),
        )

        assert resp.status_code == 200
        data = resp.json()

        # Top-level fields
        assert "correlation_id" in data
        assert "routing_decision" in data
        assert "execution" in data
        assert "columns" in data
        assert "rows" in data

        # routing_decision fields
        rd = data["routing_decision"]
        assert "engine" in rd
        assert "engine_display_name" in rd
        assert "stage" in rd
        assert "reason" in rd
        assert "complexity_score" in rd

        # execution fields
        ex = data["execution"]
        assert "execution_time_ms" in ex
        assert "data_scanned_bytes" in ex


# ---------------------------------------------------------------------------
# Routing logic integration
# ---------------------------------------------------------------------------


class TestRoutingIntegration:
    """Test that routing decisions are correctly reflected in the response."""

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.httpx.AsyncClient")
    def test_default_routing_mode_is_smart(self, mock_client_cls, _db):
        """When routing_mode is omitted, it defaults to 'smart'."""
        from catalog_service import TableMetadata

        meta = {
            "cat.sch.t": TableMetadata(
                full_name="cat.sch.t",
                table_type="MANAGED",
                data_source_format="DELTA",
                storage_location="s3://b/p",
                size_bytes=1000,
                has_rls=False,
                has_column_masking=False,
                external_engine_read_support=True,
                cached=True,
            )
        }

        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 200
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.json.return_value = {
            "columns": ["id"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 0.5,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with (
            patch("main.catalog_service.get_tables_metadata", return_value=meta),
            patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty),
        ):
            resp = client.post(
                "/api/query",
                json={"sql": "SELECT id FROM cat.sch.t"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        # Simple DELTA table, low complexity → DuckDB via SCORING
        assert data["routing_decision"]["engine"] == "duckdb"
        assert data["routing_decision"]["stage"] == "SCORING"


# ---------------------------------------------------------------------------
# Routing log events in response
# ---------------------------------------------------------------------------


class TestRoutingLogEvents:
    """Verify POST /api/query includes routing_log_events."""

    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_response_includes_routing_log_events(
        self, mock_client_cls, _rules, _meta, _db
    ):
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.raise_for_status = MagicMock()

        mock_exec_resp = MagicMock()
        mock_exec_resp.status_code = 200
        mock_exec_resp.headers = {"content-type": "application/json"}
        mock_exec_resp.json.return_value = {
            "columns": ["1"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 0.5,
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health_resp
        mock_client.post.return_value = mock_exec_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1", "routing_mode": "smart"},
            headers=_auth_header(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "routing_log_events" in data
        events = data["routing_log_events"]
        assert isinstance(events, list)
        assert len(events) > 0

        # Each event has the expected shape
        for event in events:
            assert "timestamp" in event
            assert "level" in event
            assert "stage" in event
            assert "message" in event

        # Should have parse, execute, and complete stages
        stages = {e["stage"] for e in events}
        assert "parse" in stages
        assert "execute" in stages
        assert "complete" in stages

        # Last event should be the completion message
        assert events[-1]["stage"] == "complete"
        assert "executed" in events[-1]["message"].lower()
