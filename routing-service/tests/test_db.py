"""Tests for db.py — PostgreSQL connection pool and query helpers.

All tests mock psycopg2 internals so no real database is needed.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import db


@pytest.fixture(autouse=True)
def reset_pool():
    """Ensure the module-level pool is None before/after each test."""
    original = db._pool
    db._pool = None
    yield
    db._pool = original


@pytest.fixture
def mock_pool():
    """Create a mock ThreadedConnectionPool and install it as db._pool."""
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()

    # conn.cursor() returns the cursor (or cursor with factory)
    conn.cursor.return_value = cursor
    # Make cursor work as a context manager
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    pool.getconn.return_value = conn
    db._pool = pool

    return {"pool": pool, "conn": conn, "cursor": cursor}


# ---------------------------------------------------------------------------
# init_db / close_db lifecycle
# ---------------------------------------------------------------------------


class TestInitDb:
    @patch("db.ThreadedConnectionPool")
    def test_init_db_creates_pool(self, mock_tpool):
        """init_db should create a ThreadedConnectionPool and verify connectivity."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        mock_pool_instance = MagicMock()
        mock_pool_instance.getconn.return_value = mock_conn
        mock_tpool.return_value = mock_pool_instance

        db.init_db()

        mock_tpool.assert_called_once()
        assert db._pool is mock_pool_instance
        # Verify the connectivity check ran
        mock_cur.execute.assert_called_with("SELECT 1")

    @patch("db.ThreadedConnectionPool")
    def test_init_db_raises_on_connection_failure(self, mock_tpool):
        """init_db should propagate exceptions from pool creation."""
        mock_tpool.side_effect = Exception("Connection refused")
        with pytest.raises(Exception, match="Connection refused"):
            db.init_db()

    def test_close_db_closes_pool(self, mock_pool):
        """close_db should call closeall() and set _pool to None."""
        db.close_db()
        mock_pool["pool"].closeall.assert_called_once()
        assert db._pool is None

    def test_close_db_noop_when_no_pool(self):
        """close_db should be safe to call when pool is None."""
        db._pool = None
        db.close_db()  # Should not raise


# ---------------------------------------------------------------------------
# get_conn context manager
# ---------------------------------------------------------------------------


class TestGetConn:
    def test_get_conn_raises_without_pool(self):
        """get_conn should raise RuntimeError when pool is not initialized."""
        db._pool = None
        with pytest.raises(RuntimeError, match="not initialized"):
            with db.get_conn():
                pass

    def test_get_conn_commits_on_success(self, mock_pool):
        """Normal exit commits the connection."""
        with db.get_conn() as conn:
            assert conn is mock_pool["conn"]
        mock_pool["conn"].commit.assert_called_once()
        mock_pool["conn"].rollback.assert_not_called()
        mock_pool["pool"].putconn.assert_called_once_with(mock_pool["conn"])

    def test_get_conn_rolls_back_on_exception(self, mock_pool):
        """Exception inside the context manager triggers rollback."""
        with pytest.raises(ValueError):
            with db.get_conn() as conn:
                raise ValueError("test error")
        mock_pool["conn"].rollback.assert_called_once()
        mock_pool["conn"].commit.assert_not_called()
        mock_pool["pool"].putconn.assert_called_once_with(mock_pool["conn"])

    def test_get_conn_returns_to_pool_even_on_error(self, mock_pool):
        """Connection is always returned to pool regardless of outcome."""
        with pytest.raises(RuntimeError):
            with db.get_conn():
                raise RuntimeError("boom")
        mock_pool["pool"].putconn.assert_called_once()


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_runs_sql(self, mock_pool):
        """execute() should run SQL with params."""
        db.execute("INSERT INTO t (a) VALUES (%s)", ("val",))
        mock_pool["cursor"].execute.assert_called_once_with(
            "INSERT INTO t (a) VALUES (%s)", ("val",)
        )

    def test_execute_without_params(self, mock_pool):
        """execute() works without params."""
        db.execute("DELETE FROM t")
        mock_pool["cursor"].execute.assert_called_once_with("DELETE FROM t", None)

    def test_execute_commits(self, mock_pool):
        """execute() should commit on success."""
        db.execute("UPDATE t SET a = 1")
        mock_pool["conn"].commit.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_one
# ---------------------------------------------------------------------------


class TestFetchOne:
    def test_fetch_one_returns_dict(self, mock_pool):
        """fetch_one should return the first row as a dict."""
        # RealDictCursor returns RealDictRow (acts like dict)
        mock_pool["cursor"].fetchone.return_value = {"id": 1, "name": "test"}
        result = db.fetch_one("SELECT * FROM t WHERE id = %s", (1,))
        assert result == {"id": 1, "name": "test"}

    def test_fetch_one_returns_none_when_no_rows(self, mock_pool):
        """fetch_one returns None when no rows match."""
        mock_pool["cursor"].fetchone.return_value = None
        result = db.fetch_one("SELECT * FROM t WHERE id = %s", (999,))
        assert result is None

    def test_fetch_one_uses_real_dict_cursor(self, mock_pool):
        """fetch_one should request a RealDictCursor."""
        from psycopg2.extras import RealDictCursor

        mock_pool["cursor"].fetchone.return_value = None
        db.fetch_one("SELECT 1")
        # cursor() was called with cursor_factory=RealDictCursor
        mock_pool["conn"].cursor.assert_called_with(cursor_factory=RealDictCursor)


# ---------------------------------------------------------------------------
# fetch_all
# ---------------------------------------------------------------------------


class TestFetchAll:
    def test_fetch_all_returns_list_of_dicts(self, mock_pool):
        """fetch_all should return all rows as a list of dicts."""
        mock_pool["cursor"].fetchall.return_value = [
            {"id": 1, "name": "a"},
            {"id": 2, "name": "b"},
        ]
        result = db.fetch_all("SELECT * FROM t")
        assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_fetch_all_empty_result(self, mock_pool):
        """fetch_all returns empty list when no rows."""
        mock_pool["cursor"].fetchall.return_value = []
        result = db.fetch_all("SELECT * FROM t WHERE 1=0")
        assert result == []

    def test_fetch_all_with_params(self, mock_pool):
        """fetch_all passes params correctly."""
        mock_pool["cursor"].fetchall.return_value = []
        db.fetch_all("SELECT * FROM t WHERE engine = %s", ("duckdb",))
        mock_pool["cursor"].execute.assert_called_once_with(
            "SELECT * FROM t WHERE engine = %s", ("duckdb",)
        )
