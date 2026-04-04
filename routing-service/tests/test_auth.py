"""Tests for auth — session store and POST /api/auth/token (Task 60)."""

import time
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
import auth
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Reset session and token stores between tests."""
    auth._user_sessions.clear()
    auth._active_tokens.clear()
    yield
    auth._user_sessions.clear()
    auth._active_tokens.clear()


# ---------------------------------------------------------------------------
# Helper: mock WorkspaceClient.current_user.me()
# ---------------------------------------------------------------------------
def _mock_workspace_client():
    """Return a mock WorkspaceClient whose .current_user.me() succeeds."""
    wc = MagicMock()
    me = MagicMock()
    me.user_name = "testuser@example.com"
    me.emails = [MagicMock(value="testuser@example.com")]
    wc.current_user.me.return_value = me
    return wc


# ---------------------------------------------------------------------------
# POST /api/auth/token
# ---------------------------------------------------------------------------
class TestCreateToken:
    @patch("auth.WorkspaceClient")
    def test_valid_pat_returns_session_token(self, mock_wc_cls):
        mock_wc_cls.return_value = _mock_workspace_client()
        # The mock needs .current_user.me() to work through the instance
        mock_wc_cls.return_value.current_user.me.return_value = (
            _mock_workspace_client().current_user.me()
        )
        resp = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://my-workspace.databricks.com",
                "access_token": "dapi_test_token_123",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["username"] == "testuser@example.com"
        assert data["email"] == "testuser@example.com"
        assert data["expires_in"] == 3600

    @patch("auth.WorkspaceClient")
    def test_valid_pat_creates_session_in_store(self, mock_wc_cls):
        mock_wc_cls.return_value = _mock_workspace_client()
        mock_wc_cls.return_value.current_user.me.return_value = (
            _mock_workspace_client().current_user.me()
        )
        resp = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://my-workspace.databricks.com",
                "access_token": "dapi_test_token_123",
            },
        )
        token = resp.json()["token"]
        assert token in auth._user_sessions
        session = auth._user_sessions[token]
        assert session.username == "testuser@example.com"
        assert session.databricks_host == "https://my-workspace.databricks.com"
        assert session.pat == "dapi_test_token_123"
        assert session.expires_at > time.time()

    @patch("auth.WorkspaceClient")
    def test_invalid_pat_returns_401(self, mock_wc_cls):
        mock_wc_cls.return_value.current_user.me.side_effect = Exception(
            "Invalid token"
        )
        resp = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://my-workspace.databricks.com",
                "access_token": "bad_token",
            },
        )
        assert resp.status_code == 401
        assert "Invalid Databricks credentials" in resp.json()["detail"]

    @patch("auth.WorkspaceClient")
    def test_multiple_sessions_coexist(self, mock_wc_cls):
        mock_wc_cls.return_value = _mock_workspace_client()
        mock_wc_cls.return_value.current_user.me.return_value = (
            _mock_workspace_client().current_user.me()
        )
        resp1 = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://ws1.databricks.com",
                "access_token": "dapi_token_1",
            },
        )
        resp2 = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://ws2.databricks.com",
                "access_token": "dapi_token_2",
            },
        )
        assert resp1.json()["token"] != resp2.json()["token"]
        assert len(auth._user_sessions) == 2

    @patch("auth.WorkspaceClient")
    def test_email_fallback_to_username(self, mock_wc_cls):
        """When me.emails is empty, email falls back to user_name."""
        wc = MagicMock()
        me = MagicMock()
        me.user_name = "testuser@example.com"
        me.emails = []  # no emails
        wc.current_user.me.return_value = me
        mock_wc_cls.return_value = wc
        resp = client.post(
            "/api/auth/token",
            json={
                "databricks_host": "https://my-workspace.databricks.com",
                "access_token": "dapi_test",
            },
        )
        assert resp.json()["email"] == "testuser@example.com"


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
class TestSessionHelpers:
    def test_get_valid_session(self):
        now = time.time()
        session = auth.UserSession(
            username="user1",
            email="user1@test.com",
            databricks_host="https://host",
            pat="dapi_x",
            workspace_client=MagicMock(),
            created_at=now,
            expires_at=now + 3600,
        )
        auth._user_sessions["tok1"] = session
        assert auth._get_user_session("tok1") is session

    def test_get_expired_session_returns_none(self):
        now = time.time()
        session = auth.UserSession(
            username="user1",
            email="user1@test.com",
            databricks_host="https://host",
            pat="dapi_x",
            workspace_client=MagicMock(),
            created_at=now - 7200,
            expires_at=now - 3600,  # expired 1h ago
        )
        auth._user_sessions["tok_expired"] = session
        assert auth._get_user_session("tok_expired") is None
        assert "tok_expired" not in auth._user_sessions  # cleaned up

    def test_get_missing_session_returns_none(self):
        assert auth._get_user_session("nonexistent") is None

    def test_cleanup_removes_only_expired(self):
        now = time.time()
        auth._user_sessions["valid"] = auth.UserSession(
            username="a",
            email="a@t.com",
            databricks_host="h",
            pat="p",
            workspace_client=MagicMock(),
            created_at=now,
            expires_at=now + 3600,
        )
        auth._user_sessions["expired"] = auth.UserSession(
            username="b",
            email="b@t.com",
            databricks_host="h",
            pat="p",
            workspace_client=MagicMock(),
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        auth._cleanup_expired_sessions()
        assert "valid" in auth._user_sessions
        assert "expired" not in auth._user_sessions


# ---------------------------------------------------------------------------
# Admin login still works
# ---------------------------------------------------------------------------
class TestAdminLoginUnchanged:
    def test_admin_login_still_works(self):
        with patch.dict(
            "os.environ", {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "pass123"}
        ):
            # Reload the module-level constants
            auth.ADMIN_USERNAME = "admin"
            auth.ADMIN_PASSWORD = "pass123"
            resp = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "pass123",
                },
            )
            assert resp.status_code == 200
            assert "token" in resp.json()


# ---------------------------------------------------------------------------
# Unified verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    @patch("db.fetch_all", return_value=[])
    def test_admin_token_returns_admin_context(self, _mock_db):
        auth._active_tokens["admin-tok"] = "admin"
        resp = client.get(
            "/api/routing/rules", headers={"Authorization": "Bearer admin-tok"}
        )
        assert resp.status_code == 200  # proves admin token accepted

    @patch("db.fetch_all", return_value=[])
    def test_user_session_token_returns_user_context(self, _mock_db):
        now = time.time()
        auth._user_sessions["user-tok"] = auth.UserSession(
            username="sdk-user@example.com",
            email="sdk-user@example.com",
            databricks_host="https://host",
            pat="dapi_x",
            workspace_client=MagicMock(),
            created_at=now,
            expires_at=now + 3600,
        )
        resp = client.get(
            "/api/routing/rules", headers={"Authorization": "Bearer user-tok"}
        )
        assert resp.status_code == 200  # proves user token accepted

    def test_expired_session_returns_401(self):
        now = time.time()
        auth._user_sessions["expired-tok"] = auth.UserSession(
            username="old-user",
            email="old@test.com",
            databricks_host="https://host",
            pat="dapi_x",
            workspace_client=MagicMock(),
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        resp = client.get(
            "/api/routing/rules", headers={"Authorization": "Bearer expired-tok"}
        )
        assert resp.status_code == 401

    def test_garbage_token_returns_401(self):
        resp = client.get(
            "/api/routing/rules", headers={"Authorization": "Bearer totally-bogus"}
        )
        assert resp.status_code == 401

    def test_missing_auth_header_returns_401(self):
        resp = client.get("/api/routing/rules")
        assert resp.status_code == 401

    def _make_user_token(self):
        now = time.time()
        auth._user_sessions["user-tok-admin-test"] = auth.UserSession(
            username="sdk-user",
            email="sdk@test.com",
            databricks_host="https://host",
            pat="dapi_x",
            workspace_client=MagicMock(),
            created_at=now,
            expires_at=now + 3600,
        )
        return {"Authorization": "Bearer user-tok-admin-test"}

    def test_get_databricks_settings_rejects_user(self):
        resp = client.get("/api/settings/databricks", headers=self._make_user_token())
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]

    def test_post_databricks_settings_rejects_user(self):
        resp = client.post(
            "/api/settings/databricks",
            json={"host": "https://x.databricks.com", "token": "dapi_x"},
            headers=self._make_user_token(),
        )
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]

    def test_list_warehouses_rejects_user(self):
        resp = client.get("/api/databricks/warehouses", headers=self._make_user_token())
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]

    def test_save_warehouse_rejects_user(self):
        resp = client.put(
            "/api/settings/warehouse",
            json={"warehouse_id": "abc123"},
            headers=self._make_user_token(),
        )
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]
