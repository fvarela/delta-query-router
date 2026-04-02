"""Tests for GET /health/backends endpoint."""

from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import main
from main import app

client = TestClient(app)

# Fake engine rows matching the DB schema shape
_FAKE_DUCKDB_ENGINES = [
    {
        "id": "duckdb-1",
        "engine_type": "duckdb",
        "display_name": "DuckDB Small",
        "k8s_service_name": "duckdb-worker",
        "config": {},
        "cost_tier": 3,
        "is_active": True,
    },
    {
        "id": "duckdb-2",
        "engine_type": "duckdb",
        "display_name": "DuckDB Medium",
        "k8s_service_name": "duckdb-worker-medium",
        "config": {},
        "cost_tier": 4,
        "is_active": True,
    },
]


def _mock_httpx_ok():
    """Create a properly mocked httpx.AsyncClient for async with."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()  # sync — not awaited in code
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client  # async with returns self
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


def _mock_httpx_error(msg="Connection refused"):
    """Create a mocked httpx.AsyncClient that raises on get()."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=Exception(msg))
    return mock_client


class TestHealthBackends:
    """GET /health/backends — public endpoint, no auth required."""

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main._workspace_client", None)
    @patch("main.db.fetch_one", return_value={"?column?": 1})
    def test_all_healthy_except_databricks_not_configured(
        self, mock_fetch, mock_engines
    ):
        """PostgreSQL + DuckDB engines connected, Databricks not configured."""
        mock_client = _mock_httpx_ok()
        with patch("main.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/health/backends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["postgresql"]["status"] == "connected"
        # DB-backed engines: each engine reported by k8s_service_name
        assert data["duckdb-worker"]["status"] == "connected"
        assert data["duckdb-worker-medium"]["status"] == "connected"
        assert data["databricks"]["status"] == "not_configured"

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main._workspace_client", None)
    @patch("main.db.fetch_one", side_effect=Exception("connection refused"))
    def test_postgresql_error(self, mock_fetch, mock_engines):
        """PostgreSQL returns error when fetch_one raises."""
        mock_client = _mock_httpx_ok()
        with patch("main.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/health/backends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["postgresql"]["status"] == "error"
        assert "connection refused" in data["postgresql"]["detail"]

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main._workspace_client", None)
    @patch("main.db.fetch_one", return_value={"?column?": 1})
    def test_duckdb_worker_unreachable(self, mock_fetch, mock_engines):
        """DuckDB worker returns error when HTTP call fails."""
        mock_client = _mock_httpx_error("Connection refused")
        with patch("main.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/health/backends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["postgresql"]["status"] == "connected"
        # All engines report error when unreachable
        assert data["duckdb-worker"]["status"] == "error"
        assert "Connection refused" in data["duckdb-worker"]["detail"]

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value={"?column?": 1})
    def test_databricks_connected(self, mock_fetch, mock_engines):
        """Databricks returns connected when workspace client is set."""
        mock_client = _mock_httpx_ok()
        mock_ws = MagicMock()
        mock_ws.current_user.me.return_value = MagicMock()
        with (
            patch("main.httpx.AsyncClient", return_value=mock_client),
            patch("main._workspace_client", mock_ws),
        ):
            resp = client.get("/health/backends")
            assert resp.status_code == 200
            data = resp.json()
            assert data["databricks"]["status"] == "connected"

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value={"?column?": 1})
    def test_databricks_error(self, mock_fetch, mock_engines):
        """Databricks returns error when SDK call fails."""
        mock_client = _mock_httpx_ok()
        mock_ws = MagicMock()
        mock_ws.current_user.me.side_effect = Exception("token expired")
        with (
            patch("main.httpx.AsyncClient", return_value=mock_client),
            patch("main._workspace_client", mock_ws),
        ):
            resp = client.get("/health/backends")
            assert resp.status_code == 200
            data = resp.json()
            assert data["databricks"]["status"] == "error"
            assert "token expired" in data["databricks"]["detail"]

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    def test_no_auth_required(self, mock_engines):
        """Health endpoints are public — no Authorization header needed."""
        mock_client = _mock_httpx_ok()
        with (
            patch("main.db.fetch_one", return_value={"?column?": 1}),
            patch("main.httpx.AsyncClient", return_value=mock_client),
            patch("main._workspace_client", None),
        ):
            resp = client.get("/health/backends")
            assert resp.status_code == 200
