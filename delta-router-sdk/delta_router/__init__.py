"""Delta Router SDK — Python DB-API 2.0 interface for multi-engine SQL routing."""

__version__ = "0.1.0"

from .sql import connect, Connection
from .cursor import Cursor
from .exceptions import (
    AuthenticationError,
    QueryError,
    RoutingError,
    AccessDeniedError,
)
from .types import RoutingDecision, ColumnDescription

__all__ = [
    "connect",
    "Connection",
    "Cursor",
    "AuthenticationError",
    "QueryError",
    "RoutingError",
    "AccessDeniedError",
    "RoutingDecision",
    "ColumnDescription",
]
