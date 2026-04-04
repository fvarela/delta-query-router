"""Tests for TokenManager — authenticate, refresh, request_with_retry."""

import httpx
import pytest
import respx

from delta_router.auth import TokenManager
from delta_router.exceptions import AuthenticationError
from tests.conftest import (
    SERVER_URL,
    DATABRICKS_HOST,
    ACCESS_TOKEN,
    AUTH_RESPONSE,
)


def _make_token_manager(mock_router) -> TokenManager:
    """Create a TokenManager with a real httpx.Client intercepted by respx."""
    client = httpx.Client()
    return TokenManager(
        client=client,
        server_url=SERVER_URL,
        access_token=ACCESS_TOKEN,
        databricks_host=DATABRICKS_HOST,
    )


class TestAuthenticate:
    def test_successful_auth_stores_token(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        tm = _make_token_manager(mock_router)

        tm.authenticate()

        assert tm.get_token() == "session-token-hex-abc"

    def test_sends_correct_payload(self, mock_router):
        route = mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        tm = _make_token_manager(mock_router)

        tm.authenticate()

        assert route.called
        request = route.calls[0].request
        import json

        body = json.loads(request.content)
        assert body["databricks_host"] == DATABRICKS_HOST
        assert body["access_token"] == ACCESS_TOKEN

    def test_invalid_pat_raises_auth_error(self, mock_router):
        mock_router.post("/api/auth/token").respond(
            401, json={"detail": "Invalid Databricks credentials"}
        )
        tm = _make_token_manager(mock_router)

        with pytest.raises(AuthenticationError, match="Invalid Databricks credentials"):
            tm.authenticate()

    def test_server_error_raises_auth_error(self, mock_router):
        mock_router.post("/api/auth/token").respond(500, text="Internal Server Error")
        tm = _make_token_manager(mock_router)

        with pytest.raises(AuthenticationError, match="HTTP 500"):
            tm.authenticate()

    def test_connection_error_raises_auth_error(self, mock_router):
        mock_router.post("/api/auth/token").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        tm = _make_token_manager(mock_router)

        with pytest.raises(AuthenticationError, match="Failed to connect"):
            tm.authenticate()


class TestGetToken:
    def test_before_auth_raises_error(self, mock_router):
        tm = _make_token_manager(mock_router)

        with pytest.raises(AuthenticationError, match="Not authenticated"):
            tm.get_token()

    def test_after_auth_returns_token(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        tm = _make_token_manager(mock_router)
        tm.authenticate()

        assert tm.get_token() == "session-token-hex-abc"


class TestRefresh:
    def test_refresh_re_authenticates(self, mock_router):
        # First auth returns token A, refresh returns token B
        mock_router.post("/api/auth/token").mock(
            side_effect=[
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "token-a"}),
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "token-b"}),
            ]
        )
        tm = _make_token_manager(mock_router)
        tm.authenticate()
        assert tm.get_token() == "token-a"

        tm.refresh()
        assert tm.get_token() == "token-b"


class TestRequestWithRetry:
    def test_successful_request_no_retry(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        mock_router.get("/api/routing/rules").respond(200, json=[])

        tm = _make_token_manager(mock_router)
        tm.authenticate()

        resp = tm.request_with_retry("GET", f"{SERVER_URL}/api/routing/rules")
        assert resp.status_code == 200

    def test_401_triggers_refresh_and_retry(self, mock_router):
        # Auth succeeds, first GET returns 401, refresh succeeds, retry succeeds
        mock_router.post("/api/auth/token").mock(
            side_effect=[
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "old-token"}),
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "new-token"}),
            ]
        )
        mock_router.get("/api/routing/rules").mock(
            side_effect=[
                httpx.Response(401, json={"detail": "Token expired"}),
                httpx.Response(200, json=[{"id": 1}]),
            ]
        )

        tm = _make_token_manager(mock_router)
        tm.authenticate()

        resp = tm.request_with_retry("GET", f"{SERVER_URL}/api/routing/rules")
        assert resp.status_code == 200
        assert resp.json() == [{"id": 1}]

    def test_401_after_refresh_raises_auth_error(self, mock_router):
        # Auth succeeds, GET 401, refresh succeeds, retry still 401
        mock_router.post("/api/auth/token").mock(
            side_effect=[
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "old"}),
                httpx.Response(200, json={**AUTH_RESPONSE, "token": "new"}),
            ]
        )
        mock_router.get("/api/routing/rules").mock(
            side_effect=[
                httpx.Response(401),
                httpx.Response(401),
            ]
        )

        tm = _make_token_manager(mock_router)
        tm.authenticate()

        with pytest.raises(AuthenticationError, match="Re-authentication failed"):
            tm.request_with_retry("GET", f"{SERVER_URL}/api/routing/rules")

    def test_request_includes_auth_header(self, mock_router):
        mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
        route = mock_router.get("/api/test").respond(200, json={})

        tm = _make_token_manager(mock_router)
        tm.authenticate()

        tm.request_with_retry("GET", f"{SERVER_URL}/api/test")

        request = route.calls[0].request
        assert request.headers["authorization"] == f"Bearer {AUTH_RESPONSE['token']}"
