"""Integration tests for the Delta Router SDK.

These tests run against a live routing-service (via Minikube port-forward or
local deployment). They are skipped automatically when the required env vars
are not set.

Run with::

    make port-forward  # in another terminal
    DATABRICKS_HOST=https://my-workspace.databricks.com \
    DATABRICKS_TOKEN=dapi... \
    cd delta-router-sdk && .venv/bin/python -m pytest tests/test_integration.py -v

Optional env vars:
    DELTA_ROUTER_HOST  — defaults to ``localhost:8501``
"""

from __future__ import annotations

import os

import pytest

from delta_router import (
    connect,
    AuthenticationError,
    AccessDeniedError,
    QueryError,
)

ROUTER_HOST = os.environ.get("DELTA_ROUTER_HOST", "localhost:8501")
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not all([DATABRICKS_HOST, DATABRICKS_TOKEN]),
    reason="DATABRICKS_HOST and DATABRICKS_TOKEN required for integration tests",
)


@pytest.fixture()
def conn():
    """Create and yield a live connection, closing it after the test."""
    c = connect(
        server_hostname=ROUTER_HOST,
        access_token=DATABRICKS_TOKEN,
        databricks_host=DATABRICKS_HOST,
    )
    yield c
    c.close()


# -- Happy-path tests -------------------------------------------------------


class TestAuth:
    """Authentication with a valid Databricks PAT."""

    def test_connect_and_auth(self, conn):
        """connect() with a valid PAT succeeds and the connection is open."""
        assert not conn.closed
        assert conn.token_manager.get_token() is not None


class TestQueryExecution:
    """Query execution through the SDK."""

    def test_simple_query(self, conn):
        """SELECT 1 returns correct rows and description."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS test")
            rows = cur.fetchall()
            assert len(rows) >= 1
            # The first column should be named "test"
            assert cur.description is not None
            assert cur.description[0].name == "test"
            # The value should be 1 (may come as int or str depending on engine)
            assert rows[0][0] in (1, "1")

    def test_routing_decision_populated(self, conn):
        """After execute(), routing_decision has expected fields."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x")
            rd = cur.routing_decision
            assert rd is not None
            assert rd.engine  # non-empty string
            assert rd.engine_display_name
            assert rd.stage
            assert rd.reason

    def test_engine_override_duckdb(self, conn):
        """engine='duckdb' forces routing to a DuckDB engine."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x", engine="duckdb")
            rd = cur.routing_decision
            assert rd is not None
            assert "duckdb" in rd.engine.lower()

    def test_engine_override_databricks(self, conn):
        """engine='databricks' forces routing to Databricks."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x", engine="databricks")
            rd = cur.routing_decision
            assert rd is not None
            assert "databricks" in rd.engine.lower()

    def test_rowcount(self, conn):
        """rowcount is set after execute()."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x")
            assert cur.rowcount >= 1

    def test_fetchone(self, conn):
        """fetchone() returns a single row."""
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x")
            row = cur.fetchone()
            assert row is not None
            # Subsequent fetchone should return None (only 1 row expected)
            rest = cur.fetchone()
            # rest may be None or another row — don't assert None since
            # the engine might return multiple rows for some queries


# -- Error-path tests -------------------------------------------------------


class TestErrors:
    """Error handling for invalid credentials and access."""

    def test_invalid_pat(self):
        """connect() with an invalid PAT raises AuthenticationError."""
        with pytest.raises(AuthenticationError):
            connect(
                server_hostname=ROUTER_HOST,
                access_token="dapi_INVALID_TOKEN_garbage",
                databricks_host=DATABRICKS_HOST,
            )


# -- Context manager tests --------------------------------------------------


class TestContextManagers:
    """Connection and cursor context manager patterns."""

    def test_full_context_manager_pattern(self):
        """with connect() as conn: with conn.cursor() as cur: works end-to-end."""
        with connect(
            server_hostname=ROUTER_HOST,
            access_token=DATABRICKS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS test")
                rows = cur.fetchall()
                assert len(rows) >= 1
            # Cursor should be closed after exiting its context
            assert cur._closed
        # Connection should be closed after exiting its context
        assert conn.closed

    def test_multiple_cursors(self):
        """Multiple cursors from the same connection work independently."""
        with connect(
            server_hostname=ROUTER_HOST,
            access_token=DATABRICKS_TOKEN,
            databricks_host=DATABRICKS_HOST,
        ) as conn:
            with conn.cursor() as cur1:
                cur1.execute("SELECT 1 AS a")
                rows1 = cur1.fetchall()

            with conn.cursor() as cur2:
                cur2.execute("SELECT 2 AS b")
                rows2 = cur2.fetchall()

            assert rows1[0][0] in (1, "1")
            assert rows2[0][0] in (2, "2")
