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

import httpx

from .auth import TokenManager
from .cursor import Cursor
from .exceptions import AuthenticationError


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
        if self._closed:
            raise ValueError("Cannot create cursor on a closed connection")
        return Cursor(self)

    def close(self) -> None:
        """Close the connection and release resources."""
        if not self._closed:
            self._client.close()
            self._closed = True

    @property
    def closed(self) -> bool:
        """Whether the connection has been closed."""
        return self._closed

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False
