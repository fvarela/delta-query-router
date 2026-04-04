"""Custom exceptions for the Delta Router SDK."""


class AuthenticationError(Exception):
    """Raised when Databricks PAT is invalid, revoked, or re-authentication fails."""

    pass


class QueryError(Exception):
    """Raised when query execution fails on the routing-service."""

    pass


class RoutingError(Exception):
    """Raised when the routing pipeline fails (e.g., no engines available)."""

    pass


class AccessDeniedError(Exception):
    """Raised when the user lacks access to one or more tables in the query."""

    pass
