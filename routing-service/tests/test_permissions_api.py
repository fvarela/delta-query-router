"""Tests for permissions_api.py — metastore access and EXTERNAL USE SCHEMA endpoints."""

import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import auth
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_header():
    token = "admin-tok-perms"
    auth._active_tokens[token] = "admin"
    return {"Authorization": f"Bearer {token}"}


def _user_header():
    """Non-admin user."""
    token = "user-tok-perms"
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


def _mock_metastore_summary(external_access_enabled=True, name="my-metastore"):
    """Build a mock GetMetastoreSummaryResponse."""
    summary = MagicMock()
    summary.external_access_enabled = external_access_enabled
    summary.name = name
    return summary


def _mock_me(user_name="admin@company.com"):
    me = MagicMock()
    me.user_name = user_name
    return me


def _mock_statement_response(state_value="SUCCEEDED", error_msg=None):
    """Build a mock statement execution response."""
    from unittest.mock import PropertyMock

    resp = MagicMock()
    state = MagicMock()
    state.value = state_value
    # Match against StatementState enum values
    if state_value == "SUCCEEDED":
        from databricks.sdk.service.sql import StatementState

        resp.status.state = StatementState.SUCCEEDED
    elif state_value == "FAILED":
        from databricks.sdk.service.sql import StatementState

        resp.status.state = StatementState.FAILED
        if error_msg:
            resp.status.error.message = error_msg
        else:
            resp.status.error = None
    return resp


# ---------------------------------------------------------------------------
# GET /api/metastore/external-access  (T84)
# ---------------------------------------------------------------------------


class TestMetastoreExternalAccess:
    @patch("permissions_api._main._workspace_client")
    def test_returns_enabled(self, mock_wc):
        mock_wc.metastores.summary.return_value = _mock_metastore_summary(
            external_access_enabled=True, name="prod-metastore"
        )
        # Patch at module level since _require_workspace_client reads _main._workspace_client
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get("/api/metastore/external-access", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_access_enabled"] is True
        assert data["metastore_name"] == "prod-metastore"

    @patch("permissions_api._main._workspace_client")
    def test_returns_disabled(self, mock_wc):
        mock_wc.metastores.summary.return_value = _mock_metastore_summary(
            external_access_enabled=False, name="dev-metastore"
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get("/api/metastore/external-access", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_access_enabled"] is False

    @patch("permissions_api._main._workspace_client")
    def test_returns_false_when_none(self, mock_wc):
        """external_access_enabled=None should be treated as False."""
        mock_wc.metastores.summary.return_value = _mock_metastore_summary(
            external_access_enabled=None, name="unknown"
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get("/api/metastore/external-access", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["external_access_enabled"] is False

    def test_403_for_non_admin(self):
        resp = client.get("/api/metastore/external-access", headers=_user_header())
        assert resp.status_code == 403

    def test_503_when_not_configured(self):
        with patch("permissions_api._main._workspace_client", None):
            resp = client.get("/api/metastore/external-access", headers=_admin_header())
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    @patch("permissions_api._main._workspace_client")
    def test_databricks_error_propagated(self, mock_wc):
        from databricks.sdk.errors import NotFound

        mock_wc.metastores.summary.side_effect = NotFound("no metastore")
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get("/api/metastore/external-access", headers=_admin_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/databricks/catalogs/{catalog}/schemas/{schema}/external-use  (T85)
# ---------------------------------------------------------------------------


class TestExternalUseSchemaCheck:
    @patch("permissions_api._main._workspace_client")
    def test_granted(self, mock_wc):
        mock_wc.api_client.do.return_value = {
            "privilege_assignments": [
                {"principal": "user@co.com", "privileges": ["EXTERNAL_USE_SCHEMA"]}
            ]
        }
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get(
                "/api/databricks/catalogs/main/schemas/default/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_use_schema"] is True
        assert data["catalog"] == "main"
        assert data["schema"] == "default"

    @patch("permissions_api._main._workspace_client")
    def test_not_granted(self, mock_wc):
        mock_wc.api_client.do.return_value = {
            "privilege_assignments": [
                {"principal": "user@co.com", "privileges": ["USE_SCHEMA"]}
            ]
        }
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get(
                "/api/databricks/catalogs/main/schemas/default/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 200
        assert resp.json()["external_use_schema"] is False

    @patch("permissions_api._main._workspace_client")
    def test_empty_assignments(self, mock_wc):
        mock_wc.api_client.do.return_value = {"privilege_assignments": []}
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.get(
                "/api/databricks/catalogs/cat1/schemas/sch1/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 200
        assert resp.json()["external_use_schema"] is False

    def test_403_for_non_admin(self):
        resp = client.get(
            "/api/databricks/catalogs/main/schemas/default/external-use",
            headers=_user_header(),
        )
        assert resp.status_code == 403

    def test_503_when_not_configured(self):
        with patch("permissions_api._main._workspace_client", None):
            resp = client.get(
                "/api/databricks/catalogs/main/schemas/default/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/databricks/catalogs/{catalog}/schemas/{schema}/external-use  (T86)
# ---------------------------------------------------------------------------


class TestGrantExternalUseSchema:
    @patch("permissions_api._main._warehouse_id", "wh-123")
    @patch("permissions_api._main._workspace_client")
    def test_grant_success(self, mock_wc):
        mock_wc.current_user.me.return_value = _mock_me("admin@company.com")
        mock_wc.statement_execution.execute_statement.return_value = (
            _mock_statement_response("SUCCEEDED")
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.post(
                "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_use_schema"] is True
        assert data["principal"] == "admin@company.com"
        assert data["catalog"] == "mycat"
        assert data["schema"] == "mysch"

        # Verify the SQL statement was correct
        call_args = mock_wc.statement_execution.execute_statement.call_args
        assert "GRANT EXTERNAL USE SCHEMA" in call_args.kwargs.get(
            "statement", call_args[1].get("statement", "")
        )

    @patch("permissions_api._main._warehouse_id", "wh-123")
    @patch("permissions_api._main._workspace_client")
    def test_grant_sql_failure(self, mock_wc):
        mock_wc.current_user.me.return_value = _mock_me()
        mock_wc.statement_execution.execute_statement.return_value = (
            _mock_statement_response("FAILED", "Permission denied")
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.post(
                "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 502
        assert "Failed to grant" in resp.json()["detail"]

    def test_403_for_non_admin(self):
        resp = client.post(
            "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
            headers=_user_header(),
        )
        assert resp.status_code == 403

    def test_503_when_not_configured(self):
        with patch("permissions_api._main._workspace_client", None):
            resp = client.post(
                "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 503

    @patch("permissions_api._main._workspace_client", MagicMock())
    @patch("permissions_api._main._warehouse_id", None)
    def test_400_when_no_warehouse(self):
        resp = client.post(
            "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
            headers=_admin_header(),
        )
        assert resp.status_code == 400
        assert "warehouse" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# DELETE /api/databricks/catalogs/{catalog}/schemas/{schema}/external-use  (T86)
# ---------------------------------------------------------------------------


class TestRevokeExternalUseSchema:
    @patch("permissions_api._main._warehouse_id", "wh-123")
    @patch("permissions_api._main._workspace_client")
    def test_revoke_success(self, mock_wc):
        mock_wc.current_user.me.return_value = _mock_me("admin@company.com")
        mock_wc.statement_execution.execute_statement.return_value = (
            _mock_statement_response("SUCCEEDED")
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.delete(
                "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_use_schema"] is False
        assert data["principal"] == "admin@company.com"

        # Verify REVOKE SQL
        call_args = mock_wc.statement_execution.execute_statement.call_args
        assert "REVOKE EXTERNAL USE SCHEMA" in call_args.kwargs.get(
            "statement", call_args[1].get("statement", "")
        )

    @patch("permissions_api._main._warehouse_id", "wh-123")
    @patch("permissions_api._main._workspace_client")
    def test_revoke_sql_failure(self, mock_wc):
        mock_wc.current_user.me.return_value = _mock_me()
        mock_wc.statement_execution.execute_statement.return_value = (
            _mock_statement_response("FAILED", "Insufficient privileges")
        )
        with patch("permissions_api._main._workspace_client", mock_wc):
            resp = client.delete(
                "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
                headers=_admin_header(),
            )
        assert resp.status_code == 502
        assert "Failed to revoke" in resp.json()["detail"]

    def test_403_for_non_admin(self):
        resp = client.delete(
            "/api/databricks/catalogs/mycat/schemas/mysch/external-use",
            headers=_user_header(),
        )
        assert resp.status_code == 403
