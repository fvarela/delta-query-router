"""Tests for routing profiles CRUD endpoints (Phase 15, Task 100)."""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import auth
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-profiles"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _profile_row(
    id=1,
    name="Default",
    is_default=True,
    config=None,
    **overrides,
):
    base = {
        "id": id,
        "name": name,
        "is_default": is_default,
        "config": config
        or {
            "routingMode": "single",
            "singleEngineId": None,
            "activeModelId": None,
            "enabledEngineIds": [],
            "routingPriority": 0.5,
            "workspaceBinding": None,
            "warehouseMappings": [],
        },
        "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


class TestAuthRequired:
    def test_list_requires_auth(self):
        resp = client.get("/api/routing/profiles")
        assert resp.status_code == 401

    def test_create_requires_auth(self):
        resp = client.post("/api/routing/profiles", json={"name": "x"})
        assert resp.status_code == 401

    def test_get_requires_auth(self):
        resp = client.get("/api/routing/profiles/1")
        assert resp.status_code == 401

    def test_update_requires_auth(self):
        resp = client.put("/api/routing/profiles/1", json={"name": "x"})
        assert resp.status_code == 401

    def test_delete_requires_auth(self):
        resp = client.delete("/api/routing/profiles/1")
        assert resp.status_code == 401

    def test_set_default_requires_auth(self):
        resp = client.put("/api/routing/profiles/1/default")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List profiles
# ---------------------------------------------------------------------------


class TestListProfiles:
    @patch("routing_profiles_api.db.fetch_all")
    def test_list_profiles_empty(self, mock_fetch):
        mock_fetch.return_value = []
        resp = client.get("/api/routing/profiles", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("routing_profiles_api.db.fetch_all")
    def test_list_profiles_returns_formatted(self, mock_fetch):
        mock_fetch.return_value = [
            _profile_row(),
            _profile_row(id=2, name="Custom", is_default=False),
        ]
        resp = client.get("/api/routing/profiles", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["name"] == "Default"
        assert data[0]["is_default"] is True
        assert data[0]["config"]["routingMode"] == "single"
        assert "created_at" in data[0]


# ---------------------------------------------------------------------------
# Create profile
# ---------------------------------------------------------------------------


class TestCreateProfile:
    @patch("routing_profiles_api.db.fetch_one")
    def test_create_minimal(self, mock_fetch):
        mock_fetch.return_value = _profile_row(
            id=5, name="New Profile", is_default=False
        )
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "New Profile"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "New Profile"
        # Verify SQL was called with correct params
        call_args = mock_fetch.call_args
        assert "INSERT INTO routing_profiles" in call_args[0][0]

    @patch("routing_profiles_api.db.fetch_one")
    def test_create_with_config(self, mock_fetch):
        config = {
            "routingMode": "smart",
            "singleEngineId": None,
            "activeModelId": 1,
            "enabledEngineIds": ["duckdb-1", "databricks-serverless-xs"],
            "routingPriority": 1,
            "workspaceBinding": None,
            "warehouseMappings": [],
        }
        mock_fetch.return_value = _profile_row(
            id=6, name="Smart Profile", is_default=False, config=config
        )
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Smart Profile", "config": config},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["config"]["routingMode"] == "smart"
        assert data["config"]["enabledEngineIds"] == [
            "duckdb-1",
            "databricks-serverless-xs",
        ]

    def test_create_empty_name_rejected(self):
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "  "},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_create_invalid_routing_mode(self):
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Bad", "config": {"routingMode": "invalid"}},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_create_invalid_routing_priority(self):
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Bad", "config": {"routingPriority": 0.7}},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Get profile
# ---------------------------------------------------------------------------


class TestGetProfile:
    @patch("routing_profiles_api.db.fetch_one")
    def test_get_existing(self, mock_fetch):
        mock_fetch.return_value = _profile_row()
        resp = client.get("/api/routing/profiles/1", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    @patch("routing_profiles_api.db.fetch_one")
    def test_get_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        resp = client.get("/api/routing/profiles/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update profile
# ---------------------------------------------------------------------------


class TestUpdateProfile:
    @patch("routing_profiles_api.db.fetch_one")
    def test_update_name(self, mock_fetch):
        # First call: find existing. Second call: UPDATE RETURNING
        mock_fetch.side_effect = [
            _profile_row(),
            _profile_row(name="Renamed"),
        ]
        resp = client.put(
            "/api/routing/profiles/1",
            json={"name": "Renamed"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    @patch("routing_profiles_api.db.fetch_one")
    def test_update_config(self, mock_fetch):
        new_config = {
            "routingMode": "benchmark",
            "singleEngineId": None,
            "activeModelId": None,
            "enabledEngineIds": [],
            "routingPriority": 0,
            "workspaceBinding": None,
            "warehouseMappings": [],
        }
        mock_fetch.side_effect = [
            _profile_row(),
            _profile_row(config=new_config),
        ]
        resp = client.put(
            "/api/routing/profiles/1",
            json={"config": new_config},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["routingMode"] == "benchmark"

    @patch("routing_profiles_api.db.fetch_one")
    def test_update_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        resp = client.put(
            "/api/routing/profiles/999",
            json={"name": "x"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    @patch("routing_profiles_api.db.fetch_one")
    def test_update_empty_body_returns_existing(self, mock_fetch):
        mock_fetch.return_value = _profile_row()
        resp = client.put(
            "/api/routing/profiles/1",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1


# ---------------------------------------------------------------------------
# Delete profile
# ---------------------------------------------------------------------------


class TestDeleteProfile:
    @patch("routing_profiles_api.db.execute")
    @patch("routing_profiles_api.db.fetch_one")
    def test_delete_non_default(self, mock_fetch, mock_execute):
        mock_fetch.return_value = _profile_row(id=2, is_default=False)
        resp = client.delete("/api/routing/profiles/2", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        mock_execute.assert_called_once()

    @patch("routing_profiles_api.db.fetch_one")
    def test_delete_default_rejected(self, mock_fetch):
        mock_fetch.return_value = _profile_row(is_default=True)
        resp = client.delete("/api/routing/profiles/1", headers=_auth_header())
        assert resp.status_code == 400
        assert "default" in resp.json()["detail"].lower()

    @patch("routing_profiles_api.db.fetch_one")
    def test_delete_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        resp = client.delete("/api/routing/profiles/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Set default
# ---------------------------------------------------------------------------


class TestSetDefault:
    @patch("routing_profiles_api.db.fetch_one")
    @patch("routing_profiles_api.db.get_conn")
    def test_set_default(self, mock_conn, mock_fetch):
        # Setup mock connection context manager
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        # First call: check profile exists. Second call: return updated profile
        mock_fetch.side_effect = [
            _profile_row(id=2, is_default=False),
            _profile_row(id=2, is_default=True),
        ]
        resp = client.put("/api/routing/profiles/2/default", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["is_default"] is True

        # Verify both UPDATE queries were executed
        assert mock_cursor.execute.call_count == 2

    @patch("routing_profiles_api.db.fetch_one")
    def test_set_default_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        resp = client.put("/api/routing/profiles/999/default", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validation edge cases
# ---------------------------------------------------------------------------


class TestValidation:
    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_mode_single(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingMode": "single"}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_mode_smart(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingMode": "smart"}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_mode_benchmark(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingMode": "benchmark"}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_priority_zero(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingPriority": 0}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_priority_half(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingPriority": 0.5}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    @patch("routing_profiles_api.db.fetch_one")
    def test_routing_priority_one(self, mock_fetch):
        mock_fetch.return_value = _profile_row(id=10, name="Test", is_default=False)
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingPriority": 1}},
            headers=_auth_header(),
        )
        assert resp.status_code == 201

    def test_routing_priority_invalid(self):
        resp = client.post(
            "/api/routing/profiles",
            json={"name": "Test", "config": {"routingPriority": 0.3}},
            headers=_auth_header(),
        )
        assert resp.status_code == 422
