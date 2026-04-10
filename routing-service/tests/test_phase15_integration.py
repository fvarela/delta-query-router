"""Phase 15 integration smoke test (Task 108).

Exercises the full flow across profiles, collections, benchmarks, and TPC-DS
detection to verify all Phase 15 features work together through the FastAPI
TestClient.
"""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

import auth
import main
from main import app

client = TestClient(app)


def _auth_header():
    token = "test-token-integration"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


# Stub db module for all tests
@pytest.fixture(autouse=True)
def _reset_state():
    """Reset routing engine rule cache between tests."""
    import routing_engine

    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0
    yield
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


# ---------------------------------------------------------------------------
# Profiles lifecycle
# ---------------------------------------------------------------------------


class TestProfilesLifecycle:
    """Create, set default, list, delete profiles."""

    @patch("routing_profiles_api.db")
    def test_create_and_set_default(self, mock_db):
        """Create profile → set as default → verify → delete non-default."""
        headers = _auth_header()

        # 1. Create a profile
        mock_db.fetch_one.return_value = {
            "id": 10,
            "name": "My Profile",
            "config": {"routingMode": "smart", "routingPriority": 0.5},
            "is_default": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        resp = client.post(
            "/api/routing/profiles",
            json={
                "name": "My Profile",
                "config": {"routingMode": "smart", "routingPriority": 0.5},
            },
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Profile"
        assert data["config"]["routingMode"] == "smart"

        # 2. Set as default
        mock_db.fetch_one.return_value = {
            "id": 10,
            "name": "My Profile",
            "config": {"routingMode": "smart", "routingPriority": 0.5},
            "is_default": True,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        resp = client.put("/api/routing/profiles/10/default", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_default"] is True

        # 3. Attempt to delete default profile → 400
        mock_db.fetch_one.return_value = {
            "id": 10,
            "name": "My Profile",
            "is_default": True,
        }
        resp = client.delete("/api/routing/profiles/10", headers=headers)
        assert resp.status_code == 400
        assert "default" in resp.json()["detail"].lower()

        # 4. Delete non-default profile
        mock_db.fetch_one.return_value = {
            "id": 20,
            "name": "Temp Profile",
            "is_default": False,
        }
        resp = client.delete("/api/routing/profiles/20", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# Collections with tags
# ---------------------------------------------------------------------------


class TestCollectionsWithTags:
    """Create tagged collection, verify tag in response, TPC-DS protection."""

    @patch("collections_api.db")
    def test_create_tagged_collection_and_tpcds_protection(self, mock_db):
        headers = _auth_header()

        # 1. Create collection with tag='user'
        mock_db.fetch_one.return_value = {
            "id": 5,
            "name": "My Queries",
            "description": "Test collection",
            "tag": "user",
            "created_at": "2025-01-01T00:00:00",
        }
        resp = client.post(
            "/api/collections",
            json={
                "name": "My Queries",
                "description": "Test collection",
                "tag": "user",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["tag"] == "user"

        # 2. Get collection shows tag
        mock_db.fetch_one.return_value = {
            "id": 5,
            "name": "My Queries",
            "description": "Test collection",
            "tag": "user",
            "created_at": "2025-01-01T00:00:00",
        }
        mock_db.fetch_all.return_value = []
        resp = client.get("/api/collections/5", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tag"] == "user"

        # 3. TPC-DS collection blocks delete
        mock_db.fetch_one.return_value = {
            "id": 99,
            "name": "TPC-DS SF1",
            "tag": "tpcds",
        }
        resp = client.delete("/api/collections/99", headers=headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Benchmarks: definitions + runs
# ---------------------------------------------------------------------------


class TestBenchmarkDefinitionsAndRuns:
    """Create definition, list with run_count, get run details."""

    @patch("benchmarks_api.db")
    def test_list_definitions_with_run_count(self, mock_db):
        headers = _auth_header()

        mock_db.fetch_all.return_value = [
            {
                "id": 1,
                "collection_id": 5,
                "engine_id": "duckdb-1",
                "created_at": "2025-01-01T00:00:00",
                "run_count": 3,
                "latest_run": "2025-01-03T00:00:00",
            }
        ]
        resp = client.get("/api/benchmarks", headers=headers)
        assert resp.status_code == 200
        defs = resp.json()
        assert len(defs) == 1
        assert defs[0]["run_count"] == 3
        assert defs[0]["latest_run"] is not None

    @patch("benchmarks_api.db")
    def test_get_definition_with_runs(self, mock_db):
        headers = _auth_header()

        mock_db.fetch_one.return_value = {
            "id": 1,
            "collection_id": 5,
            "engine_id": "duckdb-1",
            "created_at": "2025-01-01T00:00:00",
        }
        mock_db.fetch_all.return_value = [
            {
                "id": 10,
                "definition_id": 1,
                "status": "completed",
                "started_at": "2025-01-01T00:00:00",
                "completed_at": "2025-01-01T00:01:00",
            }
        ]
        resp = client.get("/api/benchmarks/1", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["status"] == "completed"


# ---------------------------------------------------------------------------
# TPC-DS detect
# ---------------------------------------------------------------------------


class TestTpcdsDetect:
    """TPC-DS detect returns all false when no workspace."""

    def test_detect_no_workspace_all_false(self):
        headers = _auth_header()
        original_wc = main._workspace_client
        try:
            main._workspace_client = None
            resp = client.get("/api/tpcds/detect", headers=headers)
        finally:
            main._workspace_client = original_wc

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"sf1": False, "sf10": False, "sf100": False}


# ---------------------------------------------------------------------------
# Engine scale_policy
# ---------------------------------------------------------------------------


class TestEngineScalePolicy:
    """Engines list includes scale_policy."""

    @patch("engines_api.db")
    @patch("engine_state.get_engine_state", return_value="unknown")
    def test_list_engines_includes_scale_policy(self, _state, mock_db):
        headers = _auth_header()
        mock_db.fetch_all.return_value = [
            {
                "id": "duckdb-1",
                "engine_type": "duckdb",
                "display_name": "DuckDB",
                "k8s_service_name": "duckdb-worker",
                "config": {},
                "cost_tier": 3,
                "is_active": True,
                "scale_policy": "always_on",
            }
        ]
        resp = client.get("/api/engines", headers=headers)
        assert resp.status_code == 200
        engines = resp.json()
        assert len(engines) == 1
        assert engines[0]["scale_policy"] == "always_on"


# ---------------------------------------------------------------------------
# Profile-aware query routing
# ---------------------------------------------------------------------------


class TestProfileQueryIntegration:
    """Profile config flows through to query routing."""

    @patch(
        "engines_api.get_duckdb_engines",
        return_value=[
            {
                "id": "duckdb-1",
                "engine_type": "duckdb",
                "display_name": "DuckDB",
                "k8s_service_name": "duckdb-worker",
                "config": {},
                "cost_tier": 3,
                "is_active": True,
            }
        ],
    )
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", return_value=[])
    @patch("main.httpx.AsyncClient")
    def test_profile_cost_priority_routes_to_duckdb(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """Cost-optimized profile → DuckDB wins (lower cost)."""
        # Setup httpx mock
        mock_health = MagicMock(status_code=200)
        mock_health.raise_for_status = MagicMock()
        mock_exec = MagicMock(status_code=200)
        mock_exec.headers = {"content-type": "application/json"}
        mock_exec.json.return_value = {
            "columns": ["1"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 0.5,
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_health
        mock_client.post.return_value = mock_exec
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        cost_config = {"routingMode": "smart", "routingPriority": 0}
        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                {  # routing_settings
                    "fit_weight": 0.5,
                    "cost_weight": 0.5,
                    "running_bonus_duckdb": 0.05,
                    "running_bonus_databricks": 0.15,
                },
                {"config": cost_config},  # profile
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "profile_id": 1},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "duckdb"
        # Verify response shape matches frontend expectations
        assert "correlation_id" in data
        assert "routing_log_events" in data
        assert isinstance(data["routing_log_events"], list)


# ---------------------------------------------------------------------------
# Routing settings includes active_profile_id
# ---------------------------------------------------------------------------


class TestRoutingSettingsWithProfile:
    """GET /api/routing/settings includes active_profile_id."""

    @patch("main.db.fetch_one")
    def test_settings_include_active_profile_id(self, mock_fetch):
        mock_fetch.side_effect = [
            {
                "fit_weight": 0.5,
                "cost_weight": 0.5,
                "running_bonus_duckdb": 0.05,
                "running_bonus_databricks": 0.15,
            },
            {"id": 42},  # default profile
        ]
        resp = client.get("/api/routing/settings", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["active_profile_id"] == 42


# ---------------------------------------------------------------------------
# Models with training_collection_ids
# ---------------------------------------------------------------------------


class TestModelsTrainingCollections:
    """POST /api/models/train accepts collection_ids."""

    @patch("models_api.model_trainer")
    @patch("models_api.db")
    def test_train_with_collection_ids(self, mock_db, mock_trainer):
        headers = _auth_header()
        mock_trainer.train_model.return_value = {
            "model_id": 1,
            "model_name": "test-model",
            "n_samples": 100,
            "linked_engines": ["duckdb-1"],
            "rmse": 50.0,
        }
        mock_db.fetch_one.return_value = None  # no existing model

        resp = client.post(
            "/api/models/train",
            json={"collection_ids": [1, 2, 3]},
            headers=headers,
        )
        assert resp.status_code == 200
        # Verify collection_ids was passed to trainer
        call_kwargs = mock_trainer.train_model.call_args
        assert call_kwargs.kwargs.get("collection_ids") == [1, 2, 3] or (
            len(call_kwargs.args) > 0 and call_kwargs.args[-1] == [1, 2, 3]
        )
