"""Tests for GET /api/query/{correlation_id} and GET /api/logs (task 8)."""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

import main
import auth
from main import app

_UNSET = object()  # sentinel to distinguish "not passed" from explicit None

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-logs"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _make_row(
    correlation_id="aaaa-bbbb-cccc-dddd",
    query_text="SELECT 1",
    status="success",
    engine="duckdb",
    reason="Low complexity",
    complexity_score=1.5,
    submitted_at=_UNSET,
    completed_at=_UNSET,
    execution_time_ms=None,
    routing_log_events=None,
):
    """Build a dict matching the JOIN result shape from the DB."""
    if submitted_at is _UNSET:
        submitted_at = datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)
    if completed_at is _UNSET:
        completed_at = datetime(2026, 3, 26, 12, 0, 1, tzinfo=timezone.utc)
    return {
        "correlation_id": UUID(correlation_id)
        if isinstance(correlation_id, str) and len(correlation_id) > 20
        else correlation_id,
        "query_text": query_text,
        "status": status,
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "execution_time_ms": execution_time_ms,
        "engine": engine,
        "reason": reason,
        "complexity_score": complexity_score,
        "routing_log_events": routing_log_events,
    }


SAMPLE_UUID = "12345678-1234-1234-1234-123456789abc"


# ---------------------------------------------------------------------------
# GET /api/query/{correlation_id}
# ---------------------------------------------------------------------------


class TestGetQuery:
    def test_no_auth_returns_401(self):
        resp = client.get(f"/api/query/{SAMPLE_UUID}")
        assert resp.status_code == 401

    @patch("main.db.fetch_one", return_value=None)
    def test_not_found_returns_404(self, _fetch):
        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())
        assert resp.status_code == 404

    @patch("main.db.fetch_one")
    def test_returns_full_detail(self, mock_fetch):
        mock_fetch.return_value = _make_row(
            correlation_id=UUID(SAMPLE_UUID),
            query_text="SELECT count(*) FROM t",
            status="success",
            engine="databricks",
            reason="Default to Databricks",
            complexity_score=3.0,
            execution_time_ms=2500.0,
        )

        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation_id"] == SAMPLE_UUID
        assert data["query_text"] == "SELECT count(*) FROM t"
        assert data["status"] == "success"
        assert "submitted_at" in data
        assert "completed_at" in data
        assert data["execution_time_ms"] == 2500.0

        rd = data["routing_decision"]
        assert rd["engine"] == "databricks"
        assert rd["engine_display_name"] == "Databricks"
        assert rd["reason"] == "Default to Databricks"
        assert rd["complexity_score"] == 3.0

    @patch("main.db.fetch_one")
    def test_duckdb_display_name(self, mock_fetch):
        mock_fetch.return_value = _make_row(engine="duckdb")
        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())
        assert resp.json()["routing_decision"]["engine_display_name"] == "DuckDB"

    @patch("main.db.fetch_one")
    def test_null_completed_at(self, mock_fetch):
        mock_fetch.return_value = _make_row(completed_at=None)
        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())
        assert resp.json()["completed_at"] is None

    @patch("main.db.fetch_one")
    def test_returns_routing_log_events(self, mock_fetch):
        """GET /api/query/{id} includes routing_log_events from DB."""
        sample_events = [
            {
                "timestamp": "12:00:00.001",
                "level": "info",
                "stage": "parse",
                "message": "Received query",
            },
            {
                "timestamp": "12:00:00.002",
                "level": "decision",
                "stage": "engine",
                "message": "Selected engine: duckdb",
            },
        ]
        mock_fetch.return_value = _make_row(
            correlation_id=UUID(SAMPLE_UUID),
            routing_log_events=sample_events,
        )
        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_log_events"] == sample_events

    @patch("main.db.fetch_one")
    def test_null_routing_log_events(self, mock_fetch):
        """GET /api/query/{id} returns null when no events stored (old rows)."""
        mock_fetch.return_value = _make_row(
            correlation_id=UUID(SAMPLE_UUID),
            routing_log_events=None,
        )
        resp = client.get(f"/api/query/{SAMPLE_UUID}", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["routing_log_events"] is None


# ---------------------------------------------------------------------------
# GET /api/logs
# ---------------------------------------------------------------------------


class TestGetLogs:
    def test_no_auth_returns_401(self):
        resp = client.get("/api/logs")
        assert resp.status_code == 401

    @patch("main.db.fetch_all", return_value=[])
    def test_empty_returns_empty_list(self, _fetch):
        resp = client.get("/api/logs", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("main.db.fetch_all")
    def test_returns_log_entries(self, mock_fetch):
        mock_fetch.return_value = [
            _make_row(correlation_id=UUID(SAMPLE_UUID), engine="duckdb"),
        ]

        resp = client.get("/api/logs", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        entry = data[0]
        assert entry["correlation_id"] == SAMPLE_UUID
        assert entry["engine"] == "duckdb"
        assert entry["engine_display_name"] == "DuckDB"
        assert entry["status"] == "success"
        assert "timestamp" in entry
        assert "query_text" in entry
        assert "latency_ms" in entry

    @patch("main.db.fetch_all")
    def test_engine_filter_passed_to_query(self, mock_fetch):
        mock_fetch.return_value = []

        resp = client.get("/api/logs?engine=databricks", headers=_auth_header())

        assert resp.status_code == 200
        # Verify the filter was passed as a param
        call_args = mock_fetch.call_args
        assert call_args[0][1] == ("databricks",)
        assert "WHERE r.engine = %s" in call_args[0][0]

    @patch("main.db.fetch_all")
    def test_no_filter_has_no_where_clause(self, mock_fetch):
        mock_fetch.return_value = []

        resp = client.get("/api/logs", headers=_auth_header())

        call_args = mock_fetch.call_args
        assert "WHERE" not in call_args[0][0]

    @patch("main.db.fetch_all")
    def test_latency_ms_from_execution_time(self, mock_fetch):
        """latency_ms is read from execution_time_ms column."""
        mock_fetch.return_value = [
            _make_row(execution_time_ms=1234.7),
        ]
        resp = client.get("/api/logs", headers=_auth_header())
        assert resp.json()[0]["latency_ms"] == 1235  # rounded

    @patch("main.db.fetch_all")
    def test_latency_ms_null_defaults_to_zero(self, mock_fetch):
        """latency_ms defaults to 0 when execution_time_ms is NULL (old rows)."""
        mock_fetch.return_value = [
            _make_row(execution_time_ms=None),
        ]
        resp = client.get("/api/logs", headers=_auth_header())
        assert resp.json()[0]["latency_ms"] == 0
