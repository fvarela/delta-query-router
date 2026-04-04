"""Token management for the Delta Router SDK.

Handles authentication via Databricks PAT and transparent token refresh.
"""

from __future__ import annotations

import httpx

from .exceptions import AuthenticationError


class TokenManager:
    """Manages Delta Router session tokens.

    Authenticates with a Databricks PAT via POST /api/auth/token,
    stores the session token, and transparently refreshes on 401.
    """

    def __init__(
        self,
        client: httpx.Client,
        server_url: str,
        access_token: str,
        databricks_host: str,
    ) -> None:
        self._client = client
        self._server_url = server_url
        self._access_token = access_token
        self._databricks_host = databricks_host
        self._session_token: str | None = None

    def authenticate(self) -> None:
        """Exchange Databricks PAT for a Delta Router session token.

        Raises AuthenticationError if the PAT is invalid or the server
        rejects the credentials.
        """
        try:
            resp = self._client.post(
                f"{self._server_url}/api/auth/token",
                json={
                    "databricks_host": self._databricks_host,
                    "access_token": self._access_token,
                },
            )
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"Failed to connect to Delta Router: {exc}"
            ) from exc

        if resp.status_code == 401:
            detail = resp.json().get("detail", "Invalid credentials")
            raise AuthenticationError(detail)

        if resp.status_code != 200:
            raise AuthenticationError(
                f"Authentication failed (HTTP {resp.status_code}): {resp.text}"
            )

        data = resp.json()
        self._session_token = data["token"]

    def get_token(self) -> str:
        """Return the current session token.

        Raises AuthenticationError if not yet authenticated.
        """
        if self._session_token is None:
            raise AuthenticationError("Not authenticated — call authenticate() first")
        return self._session_token

    def refresh(self) -> None:
        """Re-authenticate using the stored PAT.

        Used when a 401 response indicates the session token has expired.
        Raises AuthenticationError if re-authentication fails.
        """
        self.authenticate()

    def auth_headers(self) -> dict[str, str]:
        """Return Authorization headers for API requests."""
        return {"Authorization": f"Bearer {self.get_token()}"}

    def request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request, retrying once on 401 after token refresh.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request.
            **kwargs: Passed to httpx.Client.request().

        Returns:
            httpx.Response from the server.

        Raises:
            AuthenticationError: If retry after refresh also returns 401.
        """
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_headers())
        kwargs["headers"] = headers

        resp = self._client.request(method, url, **kwargs)

        if resp.status_code == 401:
            # Token expired — refresh and retry once
            self.refresh()
            kwargs["headers"].update(self.auth_headers())
            resp = self._client.request(method, url, **kwargs)

            if resp.status_code == 401:
                raise AuthenticationError(
                    "Re-authentication failed — PAT may be revoked"
                )

        return resp
