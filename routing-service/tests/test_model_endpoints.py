"""Tests for models_api.py — model CRUD endpoints."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import auth
from main import app
import models_api

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_header():
    token = "admin-tok-models"
    auth._active_tokens[token] = "admin"
    return {"Authorization": f"Bearer {token}"}


def _user_header():
    """Non-admin user (added to _active_tokens, no admin privileges)."""
    import time

    token = "user-tok-models"
    session = auth.UserSession(
        username="regularuser",
        email="user@example.com",
        databricks_host="https://ws.databricks.com",
        pat="dapi_user_pat",
        workspace_client=MagicMock(),
        created_at=time.time(),
        expires_at=time.time() + 3600,
    )
    auth._user_sessions[token] = session
    return {"Authorization": f"Bearer {token}"}


def _model_row(
    model_id=1,
    linked_engines=None,
    is_active=False,
    r_squared=0.85,
    mae_ms=120.0,
):
    return {
        "id": model_id,
        "linked_engines": linked_engines or ["duckdb-1", "databricks-1"],
        "latency_model": {
            "r_squared": r_squared,
            "mae_ms": mae_ms,
            "model_path": "/models/model_1.joblib",
        },
        "training_queries": 50,
        "is_active": is_active,
        "created_at": "2026-04-04T10:00:00+00:00",
        "updated_at": "2026-04-04T10:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# GET /api/models — list
# ---------------------------------------------------------------------------


class TestListModels:
    @patch("models_api.db.fetch_all", return_value=[])
    def test_empty_list(self, mock_fetch):
        resp = client.get("/api/models", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("models_api.db.fetch_all")
    def test_returns_models(self, mock_fetch):
        mock_fetch.return_value = [_model_row(1), _model_row(2)]
        resp = client.get("/api/models", headers=_admin_header())
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_unauthenticated(self):
        resp = client.get("/api/models")
        assert resp.status_code == 401

    @patch("models_api.db.fetch_all", return_value=[])
    def test_non_admin_can_list(self, mock_fetch):
        """Any authenticated user can view models."""
        resp = client.get("/api/models", headers=_user_header())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/models/{id} — detail
# ---------------------------------------------------------------------------


class TestGetModel:
    @patch("models_api.db.fetch_one")
    def test_found(self, mock_fetch):
        mock_fetch.return_value = _model_row(1)
        resp = client.get("/api/models/1", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    @patch("models_api.db.fetch_one", return_value=None)
    def test_not_found(self, mock_fetch):
        resp = client.get("/api/models/999", headers=_admin_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/models/{id}/activate
# ---------------------------------------------------------------------------


class TestActivateModel:
    @patch("models_api.model_inference.invalidate_cache")
    @patch("models_api.db.execute")
    @patch("models_api.db.fetch_all")
    @patch("models_api.db.fetch_one")
    def test_activate_success(self, mock_one, mock_all, mock_exec, mock_inv):
        model = _model_row(1, linked_engines=["duckdb-1"])
        activated = {**model, "is_active": True}
        mock_one.side_effect = [model, activated]  # first: lookup, second: return
        mock_all.return_value = [{"id": "duckdb-1"}]  # engines exist

        resp = client.post("/api/models/1/activate", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True
        mock_inv.assert_called_once()

    @patch("models_api.db.fetch_one", return_value=None)
    def test_activate_not_found(self, mock_one):
        resp = client.post("/api/models/999/activate", headers=_admin_header())
        assert resp.status_code == 404

    @patch("models_api.db.fetch_all", return_value=[])
    @patch("models_api.db.fetch_one")
    def test_activate_missing_engines(self, mock_one, mock_all):
        mock_one.return_value = _model_row(
            1, linked_engines=["duckdb-1", "gone-engine"]
        )
        resp = client.post("/api/models/1/activate", headers=_admin_header())
        assert resp.status_code == 400
        assert "unregistered engines" in resp.json()["detail"]

    @patch("models_api.db.fetch_one")
    def test_activate_admin_only(self, mock_one):
        mock_one.return_value = _model_row(1)
        resp = client.post("/api/models/1/activate", headers=_user_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/models/{id}/deactivate
# ---------------------------------------------------------------------------


class TestDeactivateModel:
    @patch("models_api.model_inference.invalidate_cache")
    @patch("models_api.db.execute")
    @patch("models_api.db.fetch_one")
    def test_deactivate_success(self, mock_one, mock_exec, mock_inv):
        model = _model_row(1, is_active=True)
        deactivated = {**model, "is_active": False}
        mock_one.side_effect = [model, deactivated]
        resp = client.post("/api/models/1/deactivate", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        mock_inv.assert_called_once()

    @patch("models_api.db.fetch_one", return_value=None)
    def test_deactivate_not_found(self, mock_one):
        resp = client.post("/api/models/999/deactivate", headers=_admin_header())
        assert resp.status_code == 404

    @patch("models_api.db.fetch_one")
    def test_deactivate_admin_only(self, mock_one):
        mock_one.return_value = _model_row(1)
        resp = client.post("/api/models/1/deactivate", headers=_user_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/models/{id}
# ---------------------------------------------------------------------------


class TestDeleteModel:
    @patch("models_api.model_inference.invalidate_cache")
    @patch("models_api.db.execute")
    @patch("models_api.os.remove")
    @patch("models_api.db.fetch_one")
    def test_delete_success(self, mock_one, mock_rm, mock_exec, mock_inv):
        mock_one.return_value = _model_row(1)
        resp = client.delete("/api/models/1", headers=_admin_header())
        assert resp.status_code == 204
        mock_rm.assert_called_once_with("/models/model_1.joblib")
        mock_inv.assert_called_once()

    @patch("models_api.model_inference.invalidate_cache")
    @patch("models_api.db.execute")
    @patch("models_api.os.remove", side_effect=FileNotFoundError)
    @patch("models_api.db.fetch_one")
    def test_delete_missing_file_no_error(self, mock_one, mock_rm, mock_exec, mock_inv):
        """Deleting a model whose joblib file is already gone should still succeed."""
        mock_one.return_value = _model_row(1)
        resp = client.delete("/api/models/1", headers=_admin_header())
        assert resp.status_code == 204

    @patch("models_api.db.fetch_one", return_value=None)
    def test_delete_not_found(self, mock_one):
        resp = client.delete("/api/models/999", headers=_admin_header())
        assert resp.status_code == 404

    @patch("models_api.db.fetch_one")
    def test_delete_admin_only(self, mock_one):
        mock_one.return_value = _model_row(1)
        resp = client.delete("/api/models/1", headers=_user_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/models/train
# ---------------------------------------------------------------------------


class TestTrainEndpoint:
    @patch("models_api.model_trainer.train_model")
    def test_train_success(self, mock_train):
        mock_train.return_value = _model_row(1, r_squared=0.90, mae_ms=80.0)
        resp = client.post("/api/models/train", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["id"] == 1
        mock_train.assert_called_once_with(
            model_dir=models_api.MODEL_DIR, collection_ids=None
        )

    @patch("models_api.model_trainer.train_model")
    def test_train_with_collection_ids(self, mock_train):
        mock_train.return_value = _model_row(1)
        resp = client.post(
            "/api/models/train",
            json={"collection_ids": [1, 3, 5]},
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        mock_train.assert_called_once_with(
            model_dir=models_api.MODEL_DIR, collection_ids=[1, 3, 5]
        )

    @patch("models_api.model_trainer.train_model")
    def test_train_too_few_samples(self, mock_train):
        mock_train.side_effect = ValueError("Need at least 10 valid training samples")
        resp = client.post("/api/models/train", headers=_admin_header())
        assert resp.status_code == 400
        assert "at least 10" in resp.json()["detail"]

    @patch("models_api.model_trainer.train_model")
    def test_train_internal_error(self, mock_train):
        mock_train.side_effect = RuntimeError("something broke")
        resp = client.post("/api/models/train", headers=_admin_header())
        assert resp.status_code == 500

    def test_train_admin_only(self):
        resp = client.post("/api/models/train", headers=_user_header())
        assert resp.status_code == 403
