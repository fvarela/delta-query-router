"""Tests for connect() and Connection lifecycle."""

import httpx
import pytest
import respx

from delta_router import sql, Connection
from delta_router.cursor import Cursor
from delta_router.exceptions import AuthenticationError, QueryError
from tests.conftest import (
    SERVER_HOSTNAME,
    SERVER_URL,
    DATABRICKS_HOST,
    ACCESS_TOKEN,
    AUTH_RESPONSE,
)


class TestConnect:
    def test_returns_connection(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        assert isinstance(conn, Connection)
        assert not conn.closed
        conn.close()

    def test_authenticates_immediately(self, mock_router):
        route = mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        assert route.called
        conn.close()

    def test_invalid_pat_raises_auth_error(self, mock_router):
        mock_router.post("/api/auth/token").respond(
            401, json={"detail": "Invalid Databricks credentials"}
        )
        with pytest.raises(AuthenticationError, match="Invalid Databricks credentials"):
            sql.connect(
                server_hostname=SERVER_HOSTNAME,
                access_token=ACCESS_TOKEN,
                databricks_host=DATABRICKS_HOST,
            )

    def test_http_path_accepted_but_ignored(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
            http_path="/sql/1.0/endpoints/abc123",
        )
        assert isinstance(conn, Connection)
        conn.close()

    def test_custom_scheme(self, mock_router):
        """scheme='https' changes the base URL."""
        # We need a different respx mock for https
        with respx.mock(base_url=f"https://{SERVER_HOSTNAME}") as https_router:
            https_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

            conn = sql.connect(
                server_hostname=SERVER_HOSTNAME,
                access_token=ACCESS_TOKEN,
                databricks_host=DATABRICKS_HOST,
                scheme="https",
            )
            assert conn.server_url == f"https://{SERVER_HOSTNAME}"
            conn.close()


class TestConnection:
    def test_cursor_returns_cursor_instance(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )

        cur = conn.cursor()
        assert isinstance(cur, Cursor)
        conn.close()

    def test_close_sets_closed_flag(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        assert not conn.closed

        conn.close()
        assert conn.closed

    def test_close_is_idempotent(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        conn.close()
        conn.close()  # should not raise
        assert conn.closed

    def test_cursor_on_closed_connection_raises(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        conn.close()

        with pytest.raises(ValueError, match="Connection is closed"):
            conn.cursor()

    def test_context_manager_closes(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

        with sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        ) as conn:
            assert not conn.closed
        assert conn.closed

    def test_context_manager_closes_on_exception(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)

        with pytest.raises(RuntimeError):
            with sql.connect(
                server_hostname=SERVER_HOSTNAME,
                access_token=ACCESS_TOKEN,
                databricks_host=DATABRICKS_HOST,
            ) as conn:
                raise RuntimeError("boom")
        assert conn.closed

    def test_server_url_property(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        assert conn.server_url == SERVER_URL
        conn.close()

    def test_token_manager_accessible(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            access_token=ACCESS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        )
        assert conn.token_manager.get_token() == AUTH_RESPONSE["token"]
        conn.close()


# ---------------------------------------------------------------------------
# Management API methods
# ---------------------------------------------------------------------------

ENGINES_RESPONSE = [
    {
        "id": 1,
        "engine_type": "databricks",
        "display_name": "Databricks SQL",
        "is_active": True,
    },
    {
        "id": 2,
        "engine_type": "duckdb",
        "display_name": "DuckDB Small",
        "is_active": True,
    },
]

PROFILES_RESPONSE = [
    {"id": 1, "name": "default", "is_default": True, "config": {}},
    {"id": 2, "name": "cost-optimized", "is_default": False, "config": {}},
]

SINGLE_PROFILE_RESPONSE = {
    "id": 2,
    "name": "cost-optimized",
    "is_default": False,
    "config": {},
}

SETTINGS_RESPONSE = {
    "fit_weight": 0.7,
    "cost_weight": 0.3,
    "active_profile_id": 1,
}


@pytest.fixture()
def conn(mock_router):
    """Create an authenticated Connection using the mock router."""
    mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
    c = sql.connect(
        server_hostname=SERVER_HOSTNAME,
        access_token=ACCESS_TOKEN,
        databricks_host=DATABRICKS_HOST,
    )
    yield c
    c.close()


class TestListEngines:
    def test_returns_engines(self, mock_router, conn):
        mock_router.get("/api/engines").respond(200, json=ENGINES_RESPONSE)
        result = conn.list_engines()
        assert result == ENGINES_RESPONSE

    def test_sends_auth_header(self, mock_router, conn):
        route = mock_router.get("/api/engines").respond(200, json=ENGINES_RESPONSE)
        conn.list_engines()
        assert (
            route.calls[0].request.headers["authorization"]
            == f"Bearer {AUTH_RESPONSE['token']}"
        )

    def test_raises_on_error(self, mock_router, conn):
        mock_router.get("/api/engines").respond(500, json={"detail": "DB error"})
        with pytest.raises(QueryError, match="DB error"):
            conn.list_engines()

    def test_raises_on_closed_connection(self, mock_router, conn):
        conn.close()
        with pytest.raises(ValueError, match="closed"):
            conn.list_engines()


class TestListProfiles:
    def test_returns_profiles(self, mock_router, conn):
        mock_router.get("/api/routing/profiles").respond(200, json=PROFILES_RESPONSE)
        result = conn.list_profiles()
        assert result == PROFILES_RESPONSE

    def test_sends_auth_header(self, mock_router, conn):
        route = mock_router.get("/api/routing/profiles").respond(
            200, json=PROFILES_RESPONSE
        )
        conn.list_profiles()
        assert (
            route.calls[0].request.headers["authorization"]
            == f"Bearer {AUTH_RESPONSE['token']}"
        )

    def test_raises_on_error(self, mock_router, conn):
        mock_router.get("/api/routing/profiles").respond(
            500, json={"detail": "Server error"}
        )
        with pytest.raises(QueryError, match="Server error"):
            conn.list_profiles()

    def test_raises_on_closed_connection(self, mock_router, conn):
        conn.close()
        with pytest.raises(ValueError, match="closed"):
            conn.list_profiles()


class TestGetProfile:
    def test_returns_single_profile(self, mock_router, conn):
        mock_router.get("/api/routing/profiles/2").respond(
            200, json=SINGLE_PROFILE_RESPONSE
        )
        result = conn.get_profile(2)
        assert result == SINGLE_PROFILE_RESPONSE

    def test_raises_on_not_found(self, mock_router, conn):
        mock_router.get("/api/routing/profiles/999").respond(
            404, json={"detail": "Profile not found"}
        )
        with pytest.raises(QueryError, match="Profile not found"):
            conn.get_profile(999)

    def test_sends_correct_url(self, mock_router, conn):
        route = mock_router.get("/api/routing/profiles/42").respond(
            200, json=SINGLE_PROFILE_RESPONSE
        )
        conn.get_profile(42)
        assert "/api/routing/profiles/42" in str(route.calls[0].request.url)

    def test_raises_on_closed_connection(self, mock_router, conn):
        conn.close()
        with pytest.raises(ValueError, match="closed"):
            conn.get_profile(1)


class TestGetRoutingSettings:
    def test_returns_settings(self, mock_router, conn):
        mock_router.get("/api/routing/settings").respond(200, json=SETTINGS_RESPONSE)
        result = conn.get_routing_settings()
        assert result == SETTINGS_RESPONSE

    def test_sends_auth_header(self, mock_router, conn):
        route = mock_router.get("/api/routing/settings").respond(
            200, json=SETTINGS_RESPONSE
        )
        conn.get_routing_settings()
        assert (
            route.calls[0].request.headers["authorization"]
            == f"Bearer {AUTH_RESPONSE['token']}"
        )

    def test_raises_on_error(self, mock_router, conn):
        mock_router.get("/api/routing/settings").respond(
            500, json={"detail": "Internal error"}
        )
        with pytest.raises(QueryError, match="Internal error"):
            conn.get_routing_settings()

    def test_raises_on_closed_connection(self, mock_router, conn):
        conn.close()
        with pytest.raises(ValueError, match="closed"):
            conn.get_routing_settings()


class TestGetJsonRetry:
    """Test that _get_json retries on 401 (via request_with_retry)."""

    def test_401_triggers_token_refresh_and_retry(self, mock_router, conn):
        """401 on GET → refresh token → retry succeeds."""
        import httpx as _httpx

        mock_router.post("/api/auth/token").respond(
            200, json={**AUTH_RESPONSE, "token": "refreshed-token"}
        )
        mock_router.get("/api/engines").mock(
            side_effect=[
                _httpx.Response(401, json={"detail": "Token expired"}),
                _httpx.Response(200, json=ENGINES_RESPONSE),
            ]
        )
        result = conn.list_engines()
        assert result == ENGINES_RESPONSE
