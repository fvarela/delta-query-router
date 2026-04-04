"""Tests for connect() and Connection lifecycle."""

import httpx
import pytest
import respx

from delta_router import sql, Connection
from delta_router.cursor import Cursor
from delta_router.exceptions import AuthenticationError
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

        with pytest.raises(ValueError, match="closed connection"):
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
