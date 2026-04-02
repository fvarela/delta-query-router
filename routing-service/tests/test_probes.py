"""Tests for probes_api.py — storage latency probes."""

from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import auth
import probes_api
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-probes"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


_NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)

_FAKE_ENGINE = {
    "id": "duckdb-1",
    "engine_type": "duckdb",
    "display_name": "DuckDB Small",
    "k8s_service_name": "duckdb-worker",
    "config": {},
    "cost_tier": 3,
    "is_active": True,
}

_FAKE_TARGETS = [
    {"storage_location": "s3://bucket/path1", "table_name": "cat.sch.table1"},
    {
        "storage_location": "abfss://container@account.dfs.core.windows.net/path2",
        "table_name": "cat.sch.table2",
    },
]


# ---------------------------------------------------------------------------
# _get_probe_targets
# ---------------------------------------------------------------------------


class TestGetProbeTargets:
    """Test storage location extraction from table_metadata_cache."""

    @patch("probes_api.db.fetch_all")
    def test_returns_one_per_location(self, mock_all):
        mock_all.return_value = _FAKE_TARGETS
        result = probes_api._get_probe_targets()
        assert len(result) == 2
        sql = mock_all.call_args[0][0]
        assert "DISTINCT ON" in sql
        assert "external_engine_read_support" in sql

    @patch("probes_api.db.fetch_all", return_value=[])
    def test_empty_cache(self, mock_all):
        result = probes_api._get_probe_targets()
        assert result == []


# ---------------------------------------------------------------------------
# _probe_storage
# ---------------------------------------------------------------------------


class TestProbeStorage:
    """Test individual storage probe execution."""

    @pytest.mark.anyio
    async def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"columns": ["x"], "rows": [[1]], "row_count": 1}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch("probes_api.httpx.AsyncClient", return_value=mock_client):
            result = await probes_api._probe_storage(
                _FAKE_ENGINE, "cat.sch.t", "https://host", "token123"
            )

        assert result["error"] is None
        assert result["probe_time_ms"] > 0

    @pytest.mark.anyio
    async def test_http_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.json.return_value = {"detail": "DuckDB crash"}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch("probes_api.httpx.AsyncClient", return_value=mock_client):
            result = await probes_api._probe_storage(
                _FAKE_ENGINE, "cat.sch.t", "https://host", "token123"
            )

        assert result["error"] is not None
        assert result["probe_time_ms"] > 0

    @pytest.mark.anyio
    async def test_connection_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Connection refused")

        with patch("probes_api.httpx.AsyncClient", return_value=mock_client):
            result = await probes_api._probe_storage(
                _FAKE_ENGINE, "cat.sch.t", "https://host", "token123"
            )

        assert "Connection refused" in result["error"]
        assert result["probe_time_ms"] > 0


# ---------------------------------------------------------------------------
# POST /api/latency-probes/run
# ---------------------------------------------------------------------------


class TestRunProbes:
    """POST /api/latency-probes/run — run probes."""

    def test_requires_auth(self):
        resp = client.post("/api/latency-probes/run")
        assert resp.status_code == 401

    @patch("main._databricks_host", None)
    @patch("main._databricks_token", None)
    def test_no_databricks(self):
        resp = client.post("/api/latency-probes/run", headers=_auth_header())
        assert resp.status_code == 400
        assert "Databricks" in resp.json()["detail"]

    @patch("probes_api._get_probe_targets", return_value=[])
    @patch("main._databricks_host", "https://host")
    @patch("main._databricks_token", "token")
    def test_no_targets(self, mock_targets):
        resp = client.post("/api/latency-probes/run", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["probes"] == []
        assert "No cached tables" in data["message"]

    @patch("probes_api._get_probe_targets", return_value=_FAKE_TARGETS[:1])
    @patch("engines_api.get_duckdb_engines", return_value=[])
    @patch("main._databricks_host", "https://host")
    @patch("main._databricks_token", "token")
    def test_no_engines(self, mock_engines, mock_targets):
        resp = client.post("/api/latency-probes/run", headers=_auth_header())
        assert resp.status_code == 400
        assert "No active DuckDB" in resp.json()["detail"]

    @patch("probes_api._probe_storage", new_callable=AsyncMock)
    @patch("probes_api.db.execute")
    @patch("probes_api._get_probe_targets", return_value=_FAKE_TARGETS[:1])
    @patch("engines_api.get_duckdb_engines", return_value=[_FAKE_ENGINE])
    @patch("main._databricks_host", "https://host")
    @patch("main._databricks_token", "token")
    def test_success(self, mock_engines, mock_targets, mock_exec, mock_probe):
        mock_probe.return_value = {
            "probe_time_ms": 45.7,
            "bytes_read": None,
            "error": None,
        }

        # Mock the health check for finding a running engine
        mock_health = MagicMock()
        mock_health.raise_for_status = MagicMock()
        mock_httpx = AsyncMock()
        mock_httpx.__aenter__.return_value = mock_httpx
        mock_httpx.get.return_value = mock_health

        with patch("probes_api.httpx.AsyncClient", return_value=mock_httpx):
            resp = client.post("/api/latency-probes/run", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["probes"]) == 1
        assert data["probes"][0]["probe_time_ms"] == 45.7
        assert data["probes"][0]["engine_id"] == "duckdb-1"
        assert data["probes"][0]["error"] is None

        # Verify result was stored
        mock_exec.assert_called_once()
        sql = mock_exec.call_args[0][0]
        assert "storage_latency_probes" in sql

    @patch("probes_api._probe_storage", new_callable=AsyncMock)
    @patch("probes_api.db.execute")
    @patch("probes_api._get_probe_targets", return_value=_FAKE_TARGETS[:1])
    @patch("engines_api.get_duckdb_engines", return_value=[_FAKE_ENGINE])
    @patch("main._databricks_host", "https://host")
    @patch("main._databricks_token", "token")
    def test_probe_error_not_stored(
        self, mock_engines, mock_targets, mock_exec, mock_probe
    ):
        """Failed probes are returned but NOT stored in the database."""
        mock_probe.return_value = {
            "probe_time_ms": 100.0,
            "bytes_read": None,
            "error": "timeout",
        }

        mock_health = MagicMock()
        mock_health.raise_for_status = MagicMock()
        mock_httpx = AsyncMock()
        mock_httpx.__aenter__.return_value = mock_httpx
        mock_httpx.get.return_value = mock_health

        with patch("probes_api.httpx.AsyncClient", return_value=mock_httpx):
            resp = client.post("/api/latency-probes/run", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data["probes"][0]["error"] == "timeout"
        # Should NOT have stored the failed probe
        mock_exec.assert_not_called()

    @patch("probes_api._probe_storage", new_callable=AsyncMock)
    @patch("probes_api.db.execute")
    @patch("probes_api._get_probe_targets", return_value=_FAKE_TARGETS)
    @patch("engines_api.get_duckdb_engines", return_value=[_FAKE_ENGINE])
    @patch("main._databricks_host", "https://host")
    @patch("main._databricks_token", "token")
    def test_multiple_locations(
        self, mock_engines, mock_targets, mock_exec, mock_probe
    ):
        """Probes multiple storage locations."""
        mock_probe.return_value = {
            "probe_time_ms": 20.0,
            "bytes_read": None,
            "error": None,
        }

        mock_health = MagicMock()
        mock_health.raise_for_status = MagicMock()
        mock_httpx = AsyncMock()
        mock_httpx.__aenter__.return_value = mock_httpx
        mock_httpx.get.return_value = mock_health

        with patch("probes_api.httpx.AsyncClient", return_value=mock_httpx):
            resp = client.post("/api/latency-probes/run", headers=_auth_header())

        assert resp.status_code == 200
        assert len(resp.json()["probes"]) == 2
        assert mock_probe.call_count == 2
        assert mock_exec.call_count == 2


# ---------------------------------------------------------------------------
# GET /api/latency-probes
# ---------------------------------------------------------------------------


class TestListProbes:
    """GET /api/latency-probes — list latest probes."""

    @patch("probes_api.db.fetch_all")
    def test_list_all(self, mock_all):
        mock_all.return_value = [
            {
                "id": 1,
                "storage_location": "s3://bucket/path",
                "engine_id": "duckdb-1",
                "probe_time_ms": 45.0,
                "bytes_read": None,
                "measured_at": _NOW,
            },
        ]
        resp = client.get("/api/latency-probes", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        sql = mock_all.call_args[0][0]
        assert "DISTINCT ON" in sql

    @patch("probes_api.db.fetch_all")
    def test_filter_by_engine(self, mock_all):
        mock_all.return_value = []
        resp = client.get(
            "/api/latency-probes?engine_id=duckdb-1", headers=_auth_header()
        )
        assert resp.status_code == 200
        sql = mock_all.call_args[0][0]
        assert "engine_id" in sql

    def test_requires_auth(self):
        resp = client.get("/api/latency-probes")
        assert resp.status_code == 401
