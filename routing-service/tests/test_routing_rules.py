"""Tests for routing rules CRUD endpoints."""

from unittest.mock import patch, call
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
    token = "test-token-rules"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _system_rule(**overrides):
    base = {
        "id": 1,
        "priority": 1,
        "condition_type": "table_type",
        "condition_value": "VIEW",
        "target_engine": "databricks",
        "is_system": True,
        "enabled": True,
    }
    base.update(overrides)
    return base


def _user_rule(**overrides):
    base = {
        "id": 100,
        "priority": 50,
        "condition_type": "complexity",
        "condition_value": "high",
        "target_engine": "databricks",
        "is_system": False,
        "enabled": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------
class TestAuthRequired:
    def test_list_requires_auth(self):
        assert client.get("/api/routing/rules").status_code == 401

    def test_create_requires_auth(self):
        assert client.post("/api/routing/rules", json={}).status_code == 401

    def test_update_requires_auth(self):
        assert client.put("/api/routing/rules/1", json={}).status_code == 401

    def test_delete_requires_auth(self):
        assert client.delete("/api/routing/rules/1").status_code == 401

    def test_toggle_requires_auth(self):
        assert client.put("/api/routing/rules/1/toggle").status_code == 401

    def test_reset_requires_auth(self):
        assert client.post("/api/routing/rules/reset").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/routing/rules
# ---------------------------------------------------------------------------
class TestListRules:
    @patch("main.db.fetch_all", return_value=[])
    def test_empty(self, _):
        resp = client.get("/api/routing/rules", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("main.db.fetch_all")
    def test_returns_rules_ordered(self, mock_fetch):
        mock_fetch.return_value = [
            _system_rule(id=1, priority=1),
            _user_rule(id=100, priority=50),
        ]
        resp = client.get("/api/routing/rules", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 100
        # Verify ORDER BY priority is in the SQL
        sql_arg = mock_fetch.call_args[0][0]
        assert "ORDER BY priority" in sql_arg


# ---------------------------------------------------------------------------
# POST /api/routing/rules
# ---------------------------------------------------------------------------
class TestCreateRule:
    @patch("main.db.fetch_one")
    def test_creates_user_rule(self, mock_fetch):
        created = _user_rule(id=101, priority=60)
        mock_fetch.return_value = created
        resp = client.post(
            "/api/routing/rules",
            json={
                "priority": 60,
                "condition_type": "complexity",
                "condition_value": "high",
                "target_engine": "databricks",
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == 101
        # Verify is_system=false is hardcoded in the SQL
        sql_arg = mock_fetch.call_args[0][0]
        assert "false" in sql_arg.lower()

    def test_missing_fields_returns_422(self):
        resp = client.post(
            "/api/routing/rules", json={"priority": 1}, headers=_auth_header()
        )
        assert resp.status_code == 422

    @patch("main.db.fetch_one")
    def test_extra_is_system_field_ignored(self, mock_fetch):
        """Even if client sends is_system=true, our model ignores it."""
        mock_fetch.return_value = _user_rule()
        resp = client.post(
            "/api/routing/rules",
            json={
                "priority": 10,
                "condition_type": "x",
                "condition_value": "y",
                "target_engine": "duckdb",
                "is_system": True,
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# PUT /api/routing/rules/{rule_id}
# ---------------------------------------------------------------------------
class TestUpdateRule:
    @patch("main.db.fetch_one")
    def test_updates_user_rule(self, mock_fetch):
        updated = _user_rule(priority=99)
        mock_fetch.side_effect = [_user_rule(), updated]
        resp = client.put(
            "/api/routing/rules/100", json={"priority": 99}, headers=_auth_header()
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == 99

    @patch("main.db.fetch_one", return_value=None)
    def test_not_found(self, _):
        resp = client.put(
            "/api/routing/rules/999", json={"priority": 1}, headers=_auth_header()
        )
        assert resp.status_code == 404

    @patch("main.db.fetch_one", return_value=_system_rule())
    def test_system_rule_returns_403(self, _):
        resp = client.put(
            "/api/routing/rules/1", json={"priority": 99}, headers=_auth_header()
        )
        assert resp.status_code == 403

    @patch("main.db.fetch_one")
    def test_empty_body_returns_existing(self, mock_fetch):
        existing = _user_rule()
        mock_fetch.return_value = existing
        resp = client.put("/api/routing/rules/100", json={}, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == existing


# ---------------------------------------------------------------------------
# DELETE /api/routing/rules/{rule_id}
# ---------------------------------------------------------------------------
class TestDeleteRule:
    @patch("main.db.execute")
    @patch("main.db.fetch_one", return_value=_user_rule())
    def test_deletes_user_rule(self, _fetch, mock_exec):
        resp = client.delete("/api/routing/rules/100", headers=_auth_header())
        assert resp.status_code == 204
        assert resp.content == b""
        mock_exec.assert_called_once()

    @patch("main.db.fetch_one", return_value=None)
    def test_not_found(self, _):
        resp = client.delete("/api/routing/rules/999", headers=_auth_header())
        assert resp.status_code == 404

    @patch("main.db.fetch_one", return_value=_system_rule())
    def test_system_rule_returns_403(self, _):
        resp = client.delete("/api/routing/rules/1", headers=_auth_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/routing/rules/{rule_id}/toggle
# ---------------------------------------------------------------------------
class TestToggleRule:
    @patch("main.db.fetch_one")
    def test_toggles_user_rule(self, mock_fetch):
        toggled = _user_rule(enabled=False)
        mock_fetch.side_effect = [_user_rule(enabled=True), toggled]
        resp = client.put("/api/routing/rules/100/toggle", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @patch("main.db.fetch_one")
    def test_toggles_system_rule(self, mock_fetch):
        toggled = _system_rule(enabled=False)
        mock_fetch.side_effect = [_system_rule(enabled=True), toggled]
        resp = client.put("/api/routing/rules/1/toggle", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @patch("main.db.fetch_one", return_value=None)
    def test_not_found(self, _):
        resp = client.put("/api/routing/rules/999/toggle", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/routing/rules/reset
# ---------------------------------------------------------------------------
class TestResetRules:
    @patch("main.db.fetch_all")
    @patch("main.db.execute")
    def test_reset_returns_system_rules(self, mock_exec, mock_fetch):
        system_rules = [_system_rule(id=i, priority=i) for i in range(1, 6)]
        mock_fetch.return_value = system_rules
        resp = client.post("/api/routing/rules/reset", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5
        assert all(r["is_system"] for r in data)
        # Verify the 3 execute calls: delete user rules, re-seed, re-enable
        assert mock_exec.call_count == 3
        calls = [c[0][0] for c in mock_exec.call_args_list]
        assert "DELETE" in calls[0] and "is_system = false" in calls[0]
        assert "INSERT" in calls[1]
        assert "UPDATE" in calls[2] and "enabled = true" in calls[2]
