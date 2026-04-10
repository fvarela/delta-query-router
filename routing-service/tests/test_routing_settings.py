"""Tests for routing settings endpoints."""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
import auth
from main import app

client = TestClient(app)


def _auth_header():
    token = "test-token-settings"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _default_settings(**overrides):
    base = {
        "id": 1,
        "fit_weight": 0.5,
        "cost_weight": 0.5,
        "running_bonus_duckdb": 0.05,
        "running_bonus_databricks": 0.15,
        "updated_at": "2026-03-27T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------
class TestAuthRequired:
    def test_get_requires_auth(self):
        assert client.get("/api/routing/settings").status_code == 401

    def test_put_requires_auth(self):
        assert client.put("/api/routing/settings", json={}).status_code == 401


# ---------------------------------------------------------------------------
# GET /api/routing/settings
# ---------------------------------------------------------------------------
class TestGetSettings:
    @patch("main.db.fetch_one")
    def test_returns_defaults(self, mock_fetch):
        mock_fetch.side_effect = [
            _default_settings(),  # routing_settings
            {"id": 1},  # default profile
        ]
        resp = client.get("/api/routing/settings", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["fit_weight"] == 0.5
        assert data["cost_weight"] == 0.5
        assert data["running_bonus_duckdb"] == 0.05
        assert data["running_bonus_databricks"] == 0.15
        assert data["active_profile_id"] == 1

    @patch("main.db.fetch_one")
    def test_excludes_id_and_updated_at(self, mock_fetch):
        mock_fetch.side_effect = [_default_settings(), {"id": 1}]
        resp = client.get("/api/routing/settings", headers=_auth_header())
        data = resp.json()
        assert "updated_at" not in data

    @patch("main.db.fetch_one")
    def test_uninitialized_returns_500(self, mock_fetch):
        mock_fetch.return_value = None
        resp = client.get("/api/routing/settings", headers=_auth_header())
        assert resp.status_code == 500

    @patch("main.db.fetch_one")
    def test_no_default_profile_returns_null(self, mock_fetch):
        mock_fetch.side_effect = [_default_settings(), None]
        resp = client.get("/api/routing/settings", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["active_profile_id"] is None


# ---------------------------------------------------------------------------
# PUT /api/routing/settings — weight auto-complement
# ---------------------------------------------------------------------------
class TestUpdateWeights:
    @patch("main.db.fetch_one")
    def test_perf_only_auto_complements_cost(self, mock_fetch):
        mock_fetch.return_value = _default_settings(fit_weight=0.3, cost_weight=0.7)
        resp = client.put(
            "/api/routing/settings",
            json={"fit_weight": 0.3},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["fit_weight"] == 0.3
        assert resp.json()["cost_weight"] == 0.7
        # Verify both weights sent to DB
        sql_arg = mock_fetch.call_args[0][0]
        assert "fit_weight" in sql_arg
        assert "cost_weight" in sql_arg

    @patch("main.db.fetch_one")
    def test_cost_only_auto_complements_perf(self, mock_fetch):
        mock_fetch.return_value = _default_settings(fit_weight=0.2, cost_weight=0.8)
        resp = client.put(
            "/api/routing/settings",
            json={"cost_weight": 0.8},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["fit_weight"] == 0.2
        assert resp.json()["cost_weight"] == 0.8

    @patch("main.db.fetch_one")
    def test_both_weights_summing_to_one(self, mock_fetch):
        mock_fetch.return_value = _default_settings(fit_weight=0.3, cost_weight=0.7)
        resp = client.put(
            "/api/routing/settings",
            json={"fit_weight": 0.3, "cost_weight": 0.7},
            headers=_auth_header(),
        )
        assert resp.status_code == 200

    def test_both_weights_not_summing_to_one_returns_400(self):
        resp = client.put(
            "/api/routing/settings",
            json={"fit_weight": 0.5, "cost_weight": 0.6},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "sum to 1.0" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /api/routing/settings — validation
# ---------------------------------------------------------------------------
class TestUpdateValidation:
    def test_negative_bonus_duckdb(self):
        resp = client.put(
            "/api/routing/settings",
            json={"running_bonus_duckdb": -0.1},
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_negative_bonus_databricks(self):
        resp = client.put(
            "/api/routing/settings",
            json={"running_bonus_databricks": -0.5},
            headers=_auth_header(),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /api/routing/settings — empty body / bonus updates
# ---------------------------------------------------------------------------
class TestUpdateMisc:
    @patch("main.db.fetch_one", return_value=_default_settings())
    def test_empty_body_returns_current(self, mock_fetch):
        resp = client.put("/api/routing/settings", json={}, headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["fit_weight"] == 0.5

    @patch("main.db.fetch_one")
    def test_update_bonus_only(self, mock_fetch):
        mock_fetch.return_value = _default_settings(running_bonus_duckdb=0.1)
        resp = client.put(
            "/api/routing/settings",
            json={"running_bonus_duckdb": 0.1},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["running_bonus_duckdb"] == 0.1
        # Verify weights were NOT included in the update
        sql_arg = mock_fetch.call_args[0][0]
        assert "fit_weight" not in sql_arg

    @patch("main.db.fetch_one")
    def test_update_sets_updated_at(self, mock_fetch):
        mock_fetch.return_value = _default_settings()
        resp = client.put(
            "/api/routing/settings",
            json={"running_bonus_duckdb": 0.0},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        sql_arg = mock_fetch.call_args[0][0]
        assert "updated_at = NOW()" in sql_arg
