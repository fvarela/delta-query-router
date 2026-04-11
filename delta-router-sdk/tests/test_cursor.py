"""Tests for Cursor — execute, fetch*, description, routing_decision, errors."""

import httpx
import pytest
import respx

from delta_router import sql
from delta_router.cursor import Cursor
from delta_router.exceptions import AccessDeniedError, AuthenticationError, QueryError
from delta_router.types import ColumnDescription, RoutingDecision
from tests.conftest import (
    SERVER_HOSTNAME,
    SERVER_URL,
    DATABRICKS_HOST,
    ACCESS_TOKEN,
    AUTH_RESPONSE,
)

# Standard successful query response from routing-service
QUERY_RESPONSE = {
    "correlation_id": "abc-123",
    "routing_decision": {
        "engine": "duckdb",
        "engine_display_name": "DuckDB",
        "stage": "SCORING",
        "reason": "Low complexity, DuckDB-eligible tables",
        "complexity_score": 12.5,
    },
    "execution": {"execution_time_ms": 45.2},
    "columns": ["id", "name", "value"],
    "rows": [[1, "alice", 100], [2, "bob", 200], [3, "carol", 300]],
    "routing_log_events": [],
}


@pytest.fixture()
def conn(mock_router):
    """Create an authenticated Connection using the mock router."""
    mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
    c = sql.connect(
        server_hostname=SERVER_HOSTNAME,
        access_token=ACCESS_TOKEN,
        databricks_host=DATABRICKS_HOST,
    )
    yield c
    c.close()


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_stores_results(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        result = cur.execute("SELECT id, name, value FROM t")

        assert result is cur  # returns self for chaining
        assert cur.rowcount == 3
        assert cur.description is not None
        assert len(cur.description) == 3

    def test_execute_sends_correct_payload(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1")

        import json as json_mod

        body = json_mod.loads(route.calls[0].request.content)
        assert body["sql"] == "SELECT 1"
        assert "routing_mode" not in body  # no engine override

    def test_execute_with_engine_override(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1", engine="databricks")

        import json as json_mod

        body = json_mod.loads(route.calls[0].request.content)
        assert body["routing_mode"] == "databricks"

    def test_execute_with_profile_id(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1", profile_id=42)

        import json as json_mod

        body = json_mod.loads(route.calls[0].request.content)
        assert body["profile_id"] == 42

    def test_execute_with_profile_id_and_engine(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1", engine="duckdb", profile_id=7)

        import json as json_mod

        body = json_mod.loads(route.calls[0].request.content)
        assert body["routing_mode"] == "duckdb"
        assert body["profile_id"] == 7

    def test_execute_without_profile_id_omits_key(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1")

        import json as json_mod

        body = json_mod.loads(route.calls[0].request.content)
        assert "profile_id" not in body

    def test_execute_includes_auth_header(self, mock_router, conn):
        route = mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1")

        request = route.calls[0].request
        assert request.headers["authorization"] == f"Bearer {AUTH_RESPONSE['token']}"

    def test_execute_on_closed_cursor_raises(self, mock_router, conn):
        cur = conn.cursor()
        cur.close()

        with pytest.raises(ValueError, match="closed cursor"):
            cur.execute("SELECT 1")

    def test_execute_resets_cursor_position(self, mock_router, conn):
        """Second execute() resets state from first."""
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()

        cur.execute("SELECT 1")
        cur.fetchone()  # advance position
        cur.fetchone()

        # Second execute resets
        second_response = {**QUERY_RESPONSE, "rows": [[99, "z", 0]], "columns": ["x"]}
        mock_router.post("/api/query").respond(200, json=second_response)
        cur.execute("SELECT 2")

        assert cur.rowcount == 1
        assert cur.fetchone() == (99, "z", 0)


# ---------------------------------------------------------------------------
# fetchall()
# ---------------------------------------------------------------------------


class TestFetchAll:
    def test_returns_all_rows_as_tuples(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        rows = cur.fetchall()

        assert rows == [(1, "alice", 100), (2, "bob", 200), (3, "carol", 300)]

    def test_returns_remaining_rows_after_fetchone(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()  # consume first row

        rows = cur.fetchall()

        assert rows == [(2, "bob", 200), (3, "carol", 300)]

    def test_returns_empty_when_exhausted(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()

        assert cur.fetchall() == []

    def test_raises_before_execute(self, mock_router, conn):
        cur = conn.cursor()
        with pytest.raises(ValueError, match="No query has been executed"):
            cur.fetchall()


# ---------------------------------------------------------------------------
# fetchone()
# ---------------------------------------------------------------------------


class TestFetchOne:
    def test_returns_rows_sequentially(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        assert cur.fetchone() == (1, "alice", 100)
        assert cur.fetchone() == (2, "bob", 200)
        assert cur.fetchone() == (3, "carol", 300)
        assert cur.fetchone() is None

    def test_returns_none_on_empty_result(self, mock_router, conn):
        empty_resp = {**QUERY_RESPONSE, "rows": [], "columns": ["x"]}
        mock_router.post("/api/query").respond(200, json=empty_resp)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        assert cur.fetchone() is None


# ---------------------------------------------------------------------------
# fetchmany()
# ---------------------------------------------------------------------------


class TestFetchMany:
    def test_returns_requested_size(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        rows = cur.fetchmany(2)
        assert rows == [(1, "alice", 100), (2, "bob", 200)]

    def test_defaults_to_arraysize(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.arraysize = 2
        cur.execute("SELECT 1")

        rows = cur.fetchmany()
        assert len(rows) == 2

    def test_returns_remaining_when_fewer_than_size(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchmany(2)  # consume 2

        rows = cur.fetchmany(5)  # only 1 left
        assert rows == [(3, "carol", 300)]

    def test_returns_empty_when_exhausted(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()

        assert cur.fetchmany(5) == []


# ---------------------------------------------------------------------------
# description
# ---------------------------------------------------------------------------


class TestDescription:
    def test_column_names(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        assert cur.description is not None
        names = [col.name for col in cur.description]
        assert names == ["id", "name", "value"]

    def test_pep249_tuple_unpacking(self, mock_router, conn):
        """ColumnDescription can be unpacked as a 7-tuple per PEP 249."""
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        name, type_code, display_size, internal_size, precision, scale, null_ok = (
            cur.description[0]
        )
        assert name == "id"
        # Remaining fields are None by default
        assert type_code is None

    def test_none_before_execute(self, mock_router, conn):
        cur = conn.cursor()
        assert cur.description is None


# ---------------------------------------------------------------------------
# routing_decision
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_populated_after_execute(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        rd = cur.routing_decision
        assert isinstance(rd, RoutingDecision)
        assert rd.engine == "duckdb"
        assert rd.engine_display_name == "DuckDB"
        assert rd.stage == "SCORING"
        assert rd.reason == "Low complexity, DuckDB-eligible tables"
        assert rd.complexity_score == 12.5

    def test_none_before_execute(self, mock_router, conn):
        cur = conn.cursor()
        assert cur.routing_decision is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_403_raises_access_denied(self, mock_router, conn):
        mock_router.post("/api/query").respond(
            403, json={"detail": "Access denied to table(s): cat.sch.secret"}
        )
        cur = conn.cursor()

        with pytest.raises(AccessDeniedError, match="cat.sch.secret"):
            cur.execute("SELECT * FROM cat.sch.secret")

    def test_400_raises_query_error(self, mock_router, conn):
        mock_router.post("/api/query").respond(
            400, json={"detail": "Only SELECT statements are supported, got INSERT"}
        )
        cur = conn.cursor()

        with pytest.raises(QueryError, match="SELECT"):
            cur.execute("INSERT INTO t VALUES (1)")

    def test_500_raises_query_error(self, mock_router, conn):
        mock_router.post("/api/query").respond(
            500, json={"detail": "Internal server error"}
        )
        cur = conn.cursor()

        with pytest.raises(QueryError, match="Internal server error"):
            cur.execute("SELECT 1")

    def test_502_raises_query_error(self, mock_router, conn):
        mock_router.post("/api/query").respond(
            502, json={"detail": "DuckDB worker error: connection refused"}
        )
        cur = conn.cursor()

        with pytest.raises(QueryError, match="DuckDB worker error"):
            cur.execute("SELECT 1")

    def test_401_triggers_retry(self, mock_router, conn):
        """401 on query → refresh token → retry succeeds."""
        mock_router.post("/api/auth/token").respond(
            200, json={**AUTH_RESPONSE, "token": "refreshed-token"}
        )
        mock_router.post("/api/query").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "Token expired"}),
                httpx.Response(200, json=QUERY_RESPONSE),
            ]
        )
        cur = conn.cursor()

        cur.execute("SELECT 1")
        assert cur.rowcount == 3  # retry succeeded

    def test_401_after_retry_raises_auth_error(self, mock_router, conn):
        """401 on query → refresh → still 401 → AuthenticationError."""
        mock_router.post("/api/auth/token").respond(
            200, json={**AUTH_RESPONSE, "token": "refreshed-token"}
        )
        mock_router.post("/api/query").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "expired"}),
                httpx.Response(401, json={"detail": "still expired"}),
            ]
        )
        cur = conn.cursor()

        with pytest.raises(AuthenticationError, match="Re-authentication failed"):
            cur.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_closes_on_exit(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert not cur._closed

        assert cur._closed

    def test_closes_on_exception(self, mock_router, conn):
        with pytest.raises(RuntimeError):
            with conn.cursor() as cur:
                raise RuntimeError("boom")

        assert cur._closed


# ---------------------------------------------------------------------------
# Edge cases (coverage gaps)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unexpected_status_code_raises_query_error(self, mock_router, conn):
        """Non-standard HTTP status (e.g. 418) → QueryError."""
        mock_router.post("/api/query").respond(418, text="I'm a teapot")
        cur = conn.cursor()

        with pytest.raises(QueryError, match="Unexpected response.*418"):
            cur.execute("SELECT 1")

    def test_fetch_on_closed_cursor_raises(self, mock_router, conn):
        mock_router.post("/api/query").respond(200, json=QUERY_RESPONSE)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()

        with pytest.raises(ValueError, match="Cursor is closed"):
            cur.fetchall()

    def test_response_without_routing_decision(self, mock_router, conn):
        """Response missing routing_decision key → routing_decision is None."""
        resp_no_rd = {
            "columns": ["x"],
            "rows": [[1]],
        }
        mock_router.post("/api/query").respond(200, json=resp_no_rd)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        assert cur.routing_decision is None
        assert cur.fetchall() == [(1,)]
