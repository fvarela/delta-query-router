"""Tests for engines_api.py — engine registry CRUD + helpers."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

import auth
import engines_api
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-engines"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


# Sample engine rows matching DB shape
def _duckdb_engine(**overrides):
    base = {
        "id": "duckdb-1",
        "engine_type": "duckdb",
        "display_name": "DuckDB — Small",
        "config": {"memory_gb": 1, "cpu_count": 1},
        "k8s_service_name": "duckdb-worker",
        "cost_tier": 3,
        "is_active": True,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _databricks_engine(**overrides):
    base = {
        "id": "databricks-abc123",
        "engine_type": "databricks_sql",
        "display_name": "My Warehouse",
        "config": {
            "warehouse_id": "abc123",
            "cluster_size": "Small",
            "warehouse_type": "PRO",
            "runtime_state": "running",
        },
        "k8s_service_name": None,
        "cost_tier": 7,
        "is_active": True,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test get_duckdb_engines, get_all_engines, engine_url."""

    @patch("engines_api.db.fetch_all")
    def test_get_duckdb_engines(self, mock_fetch):
        engines = [_duckdb_engine()]
        mock_fetch.return_value = engines
        result = engines_api.get_duckdb_engines()
        assert result == engines
        sql = mock_fetch.call_args[0][0]
        assert "duckdb" in sql.lower()
        assert "is_active" in sql.lower()

    @patch("engines_api.db.fetch_all")
    def test_get_all_engines(self, mock_fetch):
        engines = [_duckdb_engine(), _databricks_engine()]
        mock_fetch.return_value = engines
        result = engines_api.get_all_engines()
        assert len(result) == 2

    def test_engine_url(self):
        eng = _duckdb_engine(k8s_service_name="duckdb-worker")
        assert engines_api.engine_url(eng) == "http://duckdb-worker:8002"

    def test_engine_url_missing_service_name(self):
        eng = _duckdb_engine(k8s_service_name=None)
        with pytest.raises(ValueError, match="no k8s_service_name"):
            engines_api.engine_url(eng)


# ---------------------------------------------------------------------------
# GET /api/engines
# ---------------------------------------------------------------------------


class TestListEngines:
    """GET /api/engines — list all engines with runtime status."""

    @patch("engines_api.get_all_engines")
    def test_list_duckdb_running(self, mock_all):
        """DuckDB engine with healthy probe → runtime_state=running."""
        mock_all.return_value = [_duckdb_engine()]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_resp

        with patch("engines_api.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/engines", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "duckdb-1"
        assert data[0]["runtime_state"] == "running"
        assert data[0]["scalable"] is True
        assert data[0]["engine_type"] == "duckdb"
        assert data[0]["cost_tier"] == 3

    @patch("engines_api.get_all_engines")
    def test_list_duckdb_stopped(self, mock_all):
        """DuckDB engine with failing probe → runtime_state=stopped."""
        mock_all.return_value = [_duckdb_engine()]

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection refused")

        with patch("engines_api.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/engines", headers=_auth_header())

        assert resp.status_code == 200
        assert resp.json()[0]["runtime_state"] == "stopped"

    @patch("engines_api.get_all_engines")
    def test_list_databricks_engine(self, mock_all):
        """Databricks engine gets runtime_state from config."""
        mock_all.return_value = [_databricks_engine()]

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client

        with patch("engines_api.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/engines", headers=_auth_header())

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["engine_type"] == "databricks_sql"
        assert data[0]["runtime_state"] == "running"
        assert data[0]["scalable"] is False

    @patch("engines_api.get_all_engines", return_value=[])
    def test_list_empty(self, mock_all):
        """No engines → empty list."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client

        with patch("engines_api.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/engines", headers=_auth_header())

        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self):
        """No auth header → 401."""
        resp = client.get("/api/engines")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/engines/{engine_id}
# ---------------------------------------------------------------------------


class TestGetEngine:
    """GET /api/engines/{engine_id} — single engine detail."""

    @patch("engines_api.db.fetch_one")
    def test_get_existing(self, mock_fetch):
        mock_fetch.return_value = _duckdb_engine()
        resp = client.get("/api/engines/duckdb-1", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["id"] == "duckdb-1"

    @patch("engines_api.db.fetch_one", return_value=None)
    def test_get_not_found(self, mock_fetch):
        resp = client.get("/api/engines/nonexistent", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/engines/{engine_id}
# ---------------------------------------------------------------------------


class TestUpdateEngine:
    """PUT /api/engines/{engine_id} — update engine fields."""

    @patch("engines_api.db.fetch_one")
    def test_update_display_name(self, mock_fetch):
        original = _duckdb_engine()
        updated = {**original, "display_name": "New Name"}
        mock_fetch.side_effect = [
            original,
            updated,
        ]  # first call: SELECT, second: UPDATE RETURNING

        resp = client.put(
            "/api/engines/duckdb-1",
            json={"display_name": "New Name"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "New Name"

    @patch("engines_api.db.fetch_one")
    def test_update_cost_tier(self, mock_fetch):
        original = _duckdb_engine()
        updated = {**original, "cost_tier": 8}
        mock_fetch.side_effect = [original, updated]

        resp = client.put(
            "/api/engines/duckdb-1",
            json={"cost_tier": 8},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["cost_tier"] == 8

    @patch("engines_api.db.fetch_one")
    def test_update_cost_tier_invalid(self, mock_fetch):
        mock_fetch.return_value = _duckdb_engine()
        resp = client.put(
            "/api/engines/duckdb-1",
            json={"cost_tier": 11},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "cost_tier" in resp.json()["detail"]

    @patch("engines_api.db.fetch_one", return_value=None)
    def test_update_not_found(self, mock_fetch):
        resp = client.put(
            "/api/engines/nonexistent",
            json={"display_name": "X"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    @patch("engines_api.db.fetch_one")
    def test_update_no_fields(self, mock_fetch):
        """Empty body → return existing unchanged."""
        original = _duckdb_engine()
        mock_fetch.return_value = original
        resp = client.put(
            "/api/engines/duckdb-1",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 200

    @patch("engines_api.db.fetch_one")
    def test_update_config_merges(self, mock_fetch):
        """Config update merges with existing config, not replaces."""
        original = _duckdb_engine(config={"memory_gb": 1, "cpu_count": 1})
        merged_config = {"memory_gb": 4, "cpu_count": 1}
        updated = {**original, "config": merged_config}
        mock_fetch.side_effect = [original, updated]

        resp = client.put(
            "/api/engines/duckdb-1",
            json={"config": {"memory_gb": 4}},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        # The second db.fetch_one call (UPDATE RETURNING) should have been called
        # with the merged config
        call_args = mock_fetch.call_args_list[1]
        sql = call_args[0][0]
        assert "config" in sql

    @patch("engines_api.db.fetch_one")
    def test_update_is_active(self, mock_fetch):
        original = _duckdb_engine()
        updated = {**original, "is_active": False}
        mock_fetch.side_effect = [original, updated]

        resp = client.put(
            "/api/engines/duckdb-1",
            json={"is_active": False},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# POST /api/engines/{engine_id}/scale
# ---------------------------------------------------------------------------


class TestScaleEngine:
    """POST /api/engines/{engine_id}/scale — K8s scaling."""

    @patch("engines_api.db.fetch_one", return_value=None)
    def test_scale_not_found(self, mock_fetch):
        resp = client.post(
            "/api/engines/nonexistent/scale",
            json={"replicas": 1},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    @patch("engines_api.db.fetch_one")
    def test_scale_non_duckdb_rejected(self, mock_fetch):
        mock_fetch.return_value = _databricks_engine()
        resp = client.post(
            "/api/engines/databricks-abc123/scale",
            json={"replicas": 1},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "DuckDB" in resp.json()["detail"]

    @patch("engines_api.db.fetch_one")
    def test_scale_invalid_replicas(self, mock_fetch):
        mock_fetch.return_value = _duckdb_engine()
        resp = client.post(
            "/api/engines/duckdb-1/scale",
            json={"replicas": 5},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "replicas" in resp.json()["detail"]

    @patch("engines_api.db.fetch_one")
    def test_scale_no_k8s_service(self, mock_fetch):
        mock_fetch.return_value = _duckdb_engine(k8s_service_name=None)
        resp = client.post(
            "/api/engines/duckdb-1/scale",
            json={"replicas": 1},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "k8s_service_name" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/engines/sync-databricks
# ---------------------------------------------------------------------------


class TestSyncDatabricks:
    """POST /api/engines/sync-databricks — upsert warehouses."""

    @patch("engines_api.db.fetch_one")
    def test_sync_single_warehouse(self, mock_fetch):
        mock_fetch.return_value = {
            "id": "databricks-wh1",
            "engine_type": "databricks_sql",
            "display_name": "Starter Warehouse",
            "config": json.dumps(
                {
                    "warehouse_id": "wh1",
                    "cluster_size": "Small",
                    "warehouse_type": "PRO",
                    "runtime_state": "running",
                }
            ),
            "cost_tier": 7,
            "is_active": True,
        }

        resp = client.post(
            "/api/engines/sync-databricks",
            json={
                "host": "https://test.cloud.databricks.com",
                "warehouses": [
                    {
                        "id": "wh1",
                        "name": "Starter Warehouse",
                        "state": "RUNNING",
                        "cluster_size": "Small",
                        "warehouse_type": "PRO",
                    },
                ],
            },
            headers=_auth_header(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] == 1
        assert len(data["engines"]) == 1

    @patch("engines_api.db.fetch_one")
    def test_sync_state_mapping(self, mock_fetch):
        """Verify warehouse state → runtime_state mapping."""
        mock_fetch.return_value = {"id": "databricks-wh1", "config": "{}"}

        states = {
            "RUNNING": "running",
            "STARTING": "starting",
            "RESUMING": "starting",
            "STOPPED": "stopped",
            "STOPPING": "stopped",
            "DELETED": "stopped",
            "UNKNOWN": "unknown",
        }

        for ws_state, expected_runtime in states.items():
            resp = client.post(
                "/api/engines/sync-databricks",
                json={
                    "host": "https://test.cloud.databricks.com",
                    "warehouses": [{"id": "wh1", "name": "WH", "state": ws_state}],
                },
                headers=_auth_header(),
            )
            assert resp.status_code == 200
            # Verify the INSERT call included the correct runtime_state
            call_args = mock_fetch.call_args
            config_str = call_args[0][1][2]  # 3rd param is config JSON string
            config = json.loads(config_str)
            assert config["runtime_state"] == expected_runtime, (
                f"Failed for state {ws_state}"
            )

    @patch("engines_api.db.fetch_one")
    def test_sync_skips_no_id(self, mock_fetch):
        """Warehouses without id are skipped."""
        resp = client.post(
            "/api/engines/sync-databricks",
            json={
                "host": "https://test.cloud.databricks.com",
                "warehouses": [{"name": "No ID"}],
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["synced"] == 0

    def test_sync_requires_auth(self):
        resp = client.post(
            "/api/engines/sync-databricks",
            json={"host": "https://x.com", "warehouses": []},
        )
        assert resp.status_code == 401
