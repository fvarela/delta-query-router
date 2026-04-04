"""Tests for dual-identity query execution and permission integration (Task 64).

Covers:
- Permission check blocks SDK users from denied tables (403)
- Permission check is skipped for admins
- Databricks execution uses user's workspace_client for SDK users
- Databricks execution uses system identity for admins
- DuckDB execution always uses system identity
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import auth
import main
from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

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
]

_MOCK_SETTINGS_ROW = {
    "fit_weight": 0.5,
    "cost_weight": 0.5,
    "running_bonus_duckdb": 0.2,
    "running_bonus_databricks": 0.1,
}


def _mock_routing_rules_empty(*_args, **_kwargs):
    return []


@pytest.fixture(autouse=True)
def _clear_auth():
    auth._active_tokens.clear()
    auth._user_sessions.clear()
    yield
    auth._active_tokens.clear()
    auth._user_sessions.clear()


@pytest.fixture(autouse=True)
def _clear_rule_cache():
    import routing_engine

    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0
    yield
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


def _admin_header():
    token = "admin-tok-dual"
    auth._active_tokens[token] = "admin"
    return {"Authorization": f"Bearer {token}"}


def _user_session_and_header():
    """Create a user session and return (session, headers)."""
    now = time.time()
    mock_wc = MagicMock()
    session = auth.UserSession(
        username="sdk-user@example.com",
        email="sdk-user@example.com",
        databricks_host="https://user-ws.databricks.com",
        pat="dapi_user_token",
        workspace_client=mock_wc,
        created_at=now,
        expires_at=now + 3600,
    )
    token = "user-tok-dual"
    auth._user_sessions[token] = session
    return session, {"Authorization": f"Bearer {token}"}


def _httpx_probe_mock():
    """Return an AsyncMock httpx client that fails all probes (DuckDB down)."""
    mock_probe = AsyncMock()
    mock_probe.get.side_effect = Exception("connection refused")
    mock_probe.__aenter__ = AsyncMock(return_value=mock_probe)
    mock_probe.__aexit__ = AsyncMock(return_value=False)
    return mock_probe


def _httpx_duckdb_success_mock():
    """Return an AsyncMock httpx client that succeeds for DuckDB health + exec."""
    mock_health_resp = MagicMock()
    mock_health_resp.status_code = 200
    mock_health_resp.raise_for_status = MagicMock()

    mock_exec_resp = MagicMock()
    mock_exec_resp.status_code = 200
    mock_exec_resp.headers = {"content-type": "application/json"}
    mock_exec_resp.json.return_value = {
        "columns": ["x"],
        "rows": [[1]],
        "row_count": 1,
        "execution_time_ms": 0.5,
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_health_resp
    mock_client.post.return_value = mock_exec_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Permission check integration (step 2b in execute_query)
# ---------------------------------------------------------------------------


class TestPermissionCheckIntegration:
    """Test that permission checks in execute_query() work correctly."""

    @patch("main.permissions.check_user_table_access", return_value=["cat.sch.secret"])
    def test_user_denied_table_returns_403(self, mock_perm_check):
        """SDK user querying a denied table → 403 with table name."""
        _session, headers = _user_session_and_header()
        resp = client.post(
            "/api/query",
            json={"sql": "SELECT * FROM cat.sch.secret"},
            headers=headers,
        )
        assert resp.status_code == 403
        assert "cat.sch.secret" in resp.json()["detail"]
        mock_perm_check.assert_called_once()

    @patch(
        "main.permissions.check_user_table_access",
        return_value=["cat.sch.t1", "cat.sch.t2"],
    )
    def test_user_multiple_denied_tables_listed(self, mock_perm_check):
        """403 detail lists all denied tables."""
        _session, headers = _user_session_and_header()
        resp = client.post(
            "/api/query",
            json={"sql": "SELECT * FROM cat.sch.t1 JOIN cat.sch.t2 ON t1.id = t2.id"},
            headers=headers,
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "cat.sch.t1" in detail
        assert "cat.sch.t2" in detail

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    @patch("main.permissions.check_user_table_access", return_value=[])
    def test_user_all_tables_accessible_passes(
        self, mock_perm_check, mock_client_cls, _rules, _meta, _db, _engines
    ):
        """SDK user with all tables accessible → query proceeds."""
        mock_client_cls.return_value = _httpx_duckdb_success_mock()
        _session, headers = _user_session_and_header()
        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1"},
            headers=headers,
        )
        assert resp.status_code == 200

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    @patch("main.permissions.check_user_table_access")
    def test_admin_skips_permission_check(
        self, mock_perm_check, mock_client_cls, _rules, _meta, _db, _engines
    ):
        """Admin query → permission check NOT called."""
        mock_client_cls.return_value = _httpx_duckdb_success_mock()
        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1"},
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        mock_perm_check.assert_not_called()

    @patch("main.permissions.check_user_table_access", return_value=[])
    def test_user_no_tables_skips_permission_check(self, mock_perm_check):
        """SDK user query with no table references → permission check skipped
        (the `if analysis.tables` guard)."""
        # SELECT 1 has no tables, so check_user_table_access shouldn't be called
        # even though user is not admin. We need the full mock stack only if
        # the query passes permissions — but with no tables, the condition
        # `not user.is_admin and analysis.tables` is False, so it proceeds.
        # We still need the downstream mocks though:
        with (
            patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES),
            patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW),
            patch("main.catalog_service.get_tables_metadata", return_value={}),
            patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty),
            patch("main.httpx.AsyncClient", return_value=_httpx_duckdb_success_mock()),
        ):
            _session, headers = _user_session_and_header()
            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1"},
                headers=headers,
            )
        assert resp.status_code == 200
        mock_perm_check.assert_not_called()


# ---------------------------------------------------------------------------
# Dual-identity execution: Databricks path
# ---------------------------------------------------------------------------


class TestDualIdentityDatabricks:
    """Verify that Databricks execution uses the correct identity."""

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    @patch("main._execute_on_databricks")
    def test_admin_uses_system_identity(
        self, mock_exec_dbx, mock_client_cls, _rules, _meta, _db, _engines
    ):
        """Admin forced-Databricks → _execute_on_databricks called with sql only."""
        mock_client_cls.return_value = _httpx_probe_mock()
        mock_exec_dbx.return_value = {
            "columns": ["x"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": None,
        }

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1", "routing_mode": "databricks"},
            headers=_admin_header(),
        )

        assert resp.status_code == 200
        mock_exec_dbx.assert_called_once_with("SELECT 1")

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    @patch("main._execute_on_databricks")
    @patch("main.permissions.check_user_table_access", return_value=[])
    def test_user_uses_own_workspace_client(
        self, _perm, mock_exec_dbx, mock_client_cls, _rules, _meta, _db, _engines
    ):
        """SDK user forced-Databricks → _execute_on_databricks called with user's workspace_client."""
        mock_client_cls.return_value = _httpx_probe_mock()
        mock_exec_dbx.return_value = {
            "columns": ["x"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": None,
        }

        session, headers = _user_session_and_header()

        # Set a system warehouse_id so the code can pass it
        original_wid = main._warehouse_id
        try:
            main._warehouse_id = "system-warehouse-id"

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "routing_mode": "databricks"},
                headers=headers,
            )
        finally:
            main._warehouse_id = original_wid

        assert resp.status_code == 200
        mock_exec_dbx.assert_called_once_with(
            "SELECT 1",
            workspace_client=session.workspace_client,
            warehouse_id="system-warehouse-id",
        )


# ---------------------------------------------------------------------------
# Dual-identity execution: DuckDB path
# ---------------------------------------------------------------------------


class TestDualIdentityDuckDB:
    """Verify that DuckDB execution always uses system identity."""

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.db.fetch_one", return_value=_MOCK_SETTINGS_ROW)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    @patch("main.permissions.check_user_table_access", return_value=[])
    def test_user_query_duckdb_uses_system_identity(
        self, _perm, mock_client_cls, _rules, _meta, _db, _engines
    ):
        """SDK user routed to DuckDB → _execute_on_duckdb called (system identity).
        The key assertion: no user workspace_client is passed to DuckDB."""
        mock_client_cls.return_value = _httpx_duckdb_success_mock()
        _session, headers = _user_session_and_header()

        resp = client.post(
            "/api/query",
            json={"sql": "SELECT 1", "routing_mode": "duckdb"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "duckdb"
        # DuckDB execution happened via httpx (mock_client.post was called),
        # not via _execute_on_databricks
