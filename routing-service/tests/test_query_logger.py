"""Tests for query_logger.py — background query logging (task 7)."""

from unittest.mock import MagicMock, patch, call

import pytest

import query_logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_conn_and_cursor():
    """Return (mock_conn, mock_cursor) wired together."""
    mock_cursor = MagicMock()
    # RETURNING id → fetchone returns (42,)
    mock_cursor.fetchone.return_value = (42,)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return mock_conn, mock_cursor


SAMPLE_KWARGS = dict(
    correlation_id="abc-123",
    user_id="testuser",
    sql="SELECT 1",
    status="success",
    engine="duckdb",
    reason="Low complexity",
    complexity_score=1.5,
    execution_time_ms=12.3,
    estimated_cost_usd=0.0,
)


# ---------------------------------------------------------------------------
# log_query_execution
# ---------------------------------------------------------------------------


class TestLogQueryExecution:
    @patch("query_logger.db.get_conn")
    def test_inserts_three_rows(self, mock_get_conn):
        """Should execute 3 INSERTs: query_logs, routing_decisions, cost_metrics."""
        mock_conn, mock_cursor = _mock_conn_and_cursor()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        query_logger.log_query_execution(**SAMPLE_KWARGS)

        assert mock_cursor.execute.call_count == 3

    @patch("query_logger.db.get_conn")
    def test_first_insert_is_query_logs(self, mock_get_conn):
        mock_conn, mock_cursor = _mock_conn_and_cursor()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        query_logger.log_query_execution(**SAMPLE_KWARGS)

        first_call_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "query_logs" in first_call_sql
        assert "RETURNING id" in first_call_sql

    @patch("query_logger.db.get_conn")
    def test_second_insert_is_routing_decisions(self, mock_get_conn):
        mock_conn, mock_cursor = _mock_conn_and_cursor()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        query_logger.log_query_execution(**SAMPLE_KWARGS)

        second_call_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "routing_decisions" in second_call_sql
        # Should use the returned query_log_id (42)
        second_call_params = mock_cursor.execute.call_args_list[1][0][1]
        assert second_call_params[0] == 42

    @patch("query_logger.db.get_conn")
    def test_third_insert_is_cost_metrics(self, mock_get_conn):
        mock_conn, mock_cursor = _mock_conn_and_cursor()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        query_logger.log_query_execution(**SAMPLE_KWARGS)

        third_call_sql = mock_cursor.execute.call_args_list[2][0][0]
        assert "cost_metrics" in third_call_sql
        third_call_params = mock_cursor.execute.call_args_list[2][0][1]
        assert third_call_params[0] == 42  # query_log_id
        assert third_call_params[2] == 12.3  # execution_time_ms

    @patch("query_logger.db.get_conn")
    def test_db_error_does_not_raise(self, mock_get_conn):
        """Logging failures should be swallowed, not propagated."""
        mock_get_conn.return_value.__enter__ = MagicMock(
            side_effect=RuntimeError("DB down")
        )
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        query_logger.log_query_execution(**SAMPLE_KWARGS)

    @patch("query_logger.db.get_conn")
    def test_none_execution_time_accepted(self, mock_get_conn):
        """Error-path logging passes None for execution_time_ms."""
        mock_conn, mock_cursor = _mock_conn_and_cursor()
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        kwargs = {**SAMPLE_KWARGS, "execution_time_ms": None, "status": "error"}
        query_logger.log_query_execution(**kwargs)

        assert mock_cursor.execute.call_count == 3


# ---------------------------------------------------------------------------
# submit_log
# ---------------------------------------------------------------------------


class TestSubmitLog:
    @patch("query_logger._executor")
    def test_submits_to_executor(self, mock_executor):
        """submit_log should delegate to the ThreadPoolExecutor."""
        query_logger.submit_log(**SAMPLE_KWARGS)

        mock_executor.submit.assert_called_once_with(
            query_logger.log_query_execution, **SAMPLE_KWARGS
        )
