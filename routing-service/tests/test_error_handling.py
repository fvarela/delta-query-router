"""Tests for _databricks_error_to_http() helper in main.py.

Verifies that each Databricks SDK exception (and network errors) maps to the
correct HTTP status code and a user-friendly message.
"""

import pytest
import requests as _requests

from databricks.sdk.errors import (
    BadRequest,
    DatabricksError,
    DeadlineExceeded,
    InternalError,
    InvalidState,
    NotFound,
    OperationFailed,
    OperationTimeout,
    PermissionDenied,
    TemporarilyUnavailable,
    TooManyRequests,
    Unauthenticated,
)
from fastapi import HTTPException

# Import the helper under test.  main.py has top-level side effects (FastAPI app,
# module-level state), but the helper is a pure function — safe to import.
from main import _databricks_error_to_http


# ---------------------------------------------------------------------------
# Parameterised: (exception_instance, expected_status, substring_in_detail)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc, expected_status, detail_substring",
    [
        # Auth errors
        (Unauthenticated("bad token"), 401, "Invalid or expired Databricks token"),
        (PermissionDenied("no access"), 403, "Insufficient Databricks permissions"),
        # Client errors
        (NotFound("catalog gone"), 404, "not found"),
        (InvalidState("warehouse stopped"), 409, "invalid state"),
        (TooManyRequests("slow down"), 429, "rate limit"),
        (BadRequest("bad sql"), 400, "request error"),
        # Server / transient errors
        (TemporarilyUnavailable("try later"), 503, "temporarily unavailable"),
        (DeadlineExceeded("took too long"), 504, "timed out"),
        (InternalError("oops"), 502, "internal error"),
        # Catch-all DatabricksError (simulated unknown subclass)
        (DatabricksError("mystery"), 502, "Databricks error"),
        # SDK operation errors (NOT DatabricksError subclasses)
        (OperationTimeout("long wait"), 504, "operation timed out"),
        (OperationFailed("boom"), 502, "operation failed"),
        # Network errors
        (_requests.ConnectionError("refused"), 502, "Cannot reach Databricks"),
        (_requests.Timeout("slow"), 504, "timed out"),
        # Generic fallback
        (RuntimeError("something else"), 500, "Unexpected error"),
    ],
    ids=[
        "Unauthenticated",
        "PermissionDenied",
        "NotFound",
        "InvalidState",
        "TooManyRequests",
        "BadRequest",
        "TemporarilyUnavailable",
        "DeadlineExceeded",
        "InternalError",
        "DatabricksError-catchall",
        "OperationTimeout",
        "OperationFailed",
        "ConnectionError",
        "Timeout",
        "generic-RuntimeError",
    ],
)
def test_maps_exception_to_correct_status(exc, expected_status, detail_substring):
    result = _databricks_error_to_http(exc)
    assert isinstance(result, HTTPException)
    assert result.status_code == expected_status
    assert detail_substring.lower() in result.detail.lower()


# ---------------------------------------------------------------------------
# Subclass ordering: InvalidState (subclass) must NOT fall into BadRequest
# ---------------------------------------------------------------------------
def test_invalid_state_not_caught_as_bad_request():
    """InvalidState extends BadRequest — must hit 409, not 400."""
    result = _databricks_error_to_http(InvalidState("warehouse stopped"))
    assert result.status_code == 409, "InvalidState should map to 409, not 400"


# ---------------------------------------------------------------------------
# Return type is always HTTPException (never raises directly)
# ---------------------------------------------------------------------------
def test_always_returns_http_exception():
    for exc in [
        Unauthenticated("x"),
        PermissionDenied("x"),
        NotFound("x"),
        BadRequest("x"),
        ValueError("x"),
    ]:
        result = _databricks_error_to_http(exc)
        assert isinstance(result, HTTPException)


# ---------------------------------------------------------------------------
# Unknown exception includes the class name for debugging
# ---------------------------------------------------------------------------
def test_unknown_exception_includes_class_name():
    class WeirdError(Exception):
        pass

    result = _databricks_error_to_http(WeirdError("weird"))
    assert result.status_code == 500
    assert "WeirdError" in result.detail
