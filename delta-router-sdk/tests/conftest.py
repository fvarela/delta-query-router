"""Shared fixtures for Delta Router SDK tests."""

import pytest
import httpx
import respx


# Standard mock server URL used across tests
SERVER_HOSTNAME = "test-router.example.com:8501"
SERVER_URL = f"http://{SERVER_HOSTNAME}"
DATABRICKS_HOST = "https://my-workspace.databricks.com"
ACCESS_TOKEN = "dapi_test_token_abc123"

# Standard successful auth response
AUTH_RESPONSE = {
    "token": "session-token-hex-abc",
    "username": "testuser@example.com",
    "email": "testuser@example.com",
    "expires_in": 3600,
}


@pytest.fixture()
def mock_router():
    """respx mock router scoped to a single test.

    Usage::

        def test_something(mock_router):
            mock_router.post("/api/auth/token").respond(200, json=AUTH_RESPONSE)
            ...
    """
    with respx.mock(base_url=SERVER_URL) as router:
        yield router
