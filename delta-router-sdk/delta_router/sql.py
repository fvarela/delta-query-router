"""Connection interface for the Delta Router SDK.

Usage::

    from delta_router import sql

    conn = sql.connect(
        server_hostname="localhost:8501",
        access_token="dapi...",
        databricks_host="https://my-workspace.databricks.com",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM catalog.schema.table")
        rows = cur.fetchall()
    conn.close()
"""

from __future__ import annotations

from typing import Any

import httpx

from .auth import TokenManager
from .cursor import Cursor
from .exceptions import AuthenticationError, QueryError


def connect(
    server_hostname: str,
    access_token: str,
    databricks_host: str,
    http_path: str | None = None,
    *,
    scheme: str = "http",
    timeout: float = 120.0,
) -> Connection:
    """Create a new Connection to a Delta Router instance.

    Args:
        server_hostname: Delta Router host and port (e.g. ``"localhost:8501"``).
        access_token: Databricks personal access token.
        databricks_host: Databricks workspace URL (e.g. ``"https://my-ws.databricks.com"``).
        http_path: Ignored — accepted for compatibility with ``databricks-sql-connector``.
        scheme: URL scheme (``"http"`` or ``"https"``). Defaults to ``"http"``.
        timeout: HTTP request timeout in seconds. Defaults to 120.

    Returns:
        An authenticated :class:`Connection` instance.

    Raises:
        AuthenticationError: If the Databricks PAT is invalid.
    """
    return Connection(
        server_hostname=server_hostname,
        access_token=access_token,
        databricks_host=databricks_host,
        scheme=scheme,
        timeout=timeout,
    )


class Connection:
    """A connection to a Delta Router instance.

    Authenticates immediately on creation using the Databricks PAT.
    Provides :meth:`cursor` for query execution and :meth:`close` for cleanup.
    Supports use as a context manager.
    """

    def __init__(
        self,
        server_hostname: str,
        access_token: str,
        databricks_host: str,
        scheme: str = "http",
        timeout: float = 120.0,
    ) -> None:
        self._server_url = f"{scheme}://{server_hostname}"
        self._client = httpx.Client(timeout=timeout)
        self._token_manager = TokenManager(
            client=self._client,
            server_url=self._server_url,
            access_token=access_token,
            databricks_host=databricks_host,
        )
        self._closed = False

        # Authenticate immediately
        self._token_manager.authenticate()

    @property
    def server_url(self) -> str:
        """Base URL of the Delta Router instance."""
        return self._server_url

    @property
    def token_manager(self) -> TokenManager:
        """The TokenManager handling auth for this connection."""
        return self._token_manager

    def cursor(self) -> Cursor:
        """Create a new Cursor bound to this connection.

        Raises:
            ValueError: If the connection is closed.
        """
        self._check_open()
        return Cursor(self)

    def close(self) -> None:
        """Close the connection and release resources."""
        if not self._closed:
            self._client.close()
            self._closed = True

    # ------------------------------------------------------------------
    # Management API helpers
    # ------------------------------------------------------------------

    def _get_json(self, path: str) -> Any:
        """Make an authenticated GET request and return the parsed JSON.

        Raises:
            QueryError: On non-200 responses.
            AuthenticationError: On 401 after retry.
        """
        url = f"{self._server_url}{path}"
        resp = self._token_manager.request_with_retry("GET", url)
        if resp.status_code != 200:
            detail = resp.json().get("detail", f"HTTP {resp.status_code}")
            raise QueryError(f"GET {path} failed: {detail}")
        return resp.json()

    def list_engines(self) -> list[dict[str, Any]]:
        """List all engines (active and inactive).

        Returns:
            A list of engine dicts with keys: id, engine_type, display_name,
            config, cost_tier, is_active, runtime_state, etc.
        """
        self._check_open()
        return self._get_json("/api/engines")

    def list_profiles(self) -> list[dict[str, Any]]:
        """List all routing profiles.

        Returns:
            A list of profile dicts with keys: id, name, is_default, config,
            created_at, updated_at.
        """
        self._check_open()
        return self._get_json("/api/routing/profiles")

    def get_profile(self, profile_id: int) -> dict[str, Any]:
        """Get a single routing profile by ID.

        Args:
            profile_id: The profile ID.

        Returns:
            A profile dict.

        Raises:
            QueryError: If the profile is not found.
        """
        self._check_open()
        return self._get_json(f"/api/routing/profiles/{profile_id}")

    def get_routing_settings(self) -> dict[str, Any]:
        """Get current routing settings (fit_weight, cost_weight, active_profile_id).

        Returns:
            A dict with routing settings.
        """
        self._check_open()
        return self._get_json("/api/routing/settings")

    def _check_open(self) -> None:
        """Raise if the connection is closed."""
        if self._closed:
            raise ValueError("Connection is closed")

    @property
    def closed(self) -> bool:
        """Whether the connection has been closed."""
        return self._closed

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
