"""Tests for query_features module — pre-computed AST features for ML training."""

from unittest.mock import patch, MagicMock, call

import pytest

import query_features


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _qf_row(query_id=1, **overrides):
    """Return a typical query_features row dict."""
    base = {
        "id": 1,
        "query_id": query_id,
        "statement_type": "SELECT",
        "tables": ["catalog.schema.t1"],
        "num_tables": 1,
        "num_joins": 0,
        "num_aggregations": 0,
        "num_subqueries": 0,
        "has_group_by": False,
        "has_order_by": False,
        "has_limit": False,
        "has_window_functions": False,
        "num_columns_selected": 2,
        "complexity_score": 0.0,
        "max_table_size_bytes": None,
        "total_data_bytes": None,
        "metadata_snapshot_at": None,
        "created_at": "2026-04-14T00:00:00+00:00",
        "updated_at": "2026-04-14T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# compute_and_store
# ---------------------------------------------------------------------------


class TestComputeAndStore:
    @patch("query_features.db.fetch_one")
    def test_simple_select(self, mock_fetch_one):
        """Simple SELECT produces correct AST features and upserts to DB."""
        mock_fetch_one.return_value = _qf_row()

        result = query_features.compute_and_store(
            1, "SELECT a, b FROM catalog.schema.t1 WHERE a > 1"
        )

        assert result is not None
        assert mock_fetch_one.called
        # Check the SQL is an upsert (ON CONFLICT)
        sql_arg = mock_fetch_one.call_args[0][0]
        assert "ON CONFLICT" in sql_arg
        # Check the params include the correct query_id and parsed features
        params = mock_fetch_one.call_args[0][1]
        assert params[0] == 1  # query_id
        assert params[1] == "SELECT"  # statement_type
        assert "catalog.schema.t1" in params[2]  # tables array

    @patch("query_features.db.fetch_one")
    def test_complex_query(self, mock_fetch_one):
        """Query with joins, aggregations, subqueries produces correct counts."""
        mock_fetch_one.return_value = _qf_row(num_joins=2, num_aggregations=1)

        sql = """
        SELECT t1.a, COUNT(t2.b)
        FROM catalog.schema.t1
        JOIN catalog.schema.t2 ON t1.id = t2.id
        JOIN catalog.schema.t3 ON t1.id = t3.id
        WHERE t1.a IN (SELECT x FROM catalog.schema.t4)
        GROUP BY t1.a
        ORDER BY COUNT(t2.b) DESC
        """
        result = query_features.compute_and_store(1, sql)

        assert result is not None
        params = mock_fetch_one.call_args[0][1]
        # query_id, statement_type, tables, num_tables, num_joins, num_agg,
        # num_subq, group_by, order_by, limit, window, cols, complexity
        assert params[0] == 1  # query_id
        assert params[3] >= 3  # num_tables (t1, t2, t3, t4)
        assert params[4] == 2  # num_joins
        assert params[5] >= 1  # num_aggregations (COUNT)
        assert params[6] >= 1  # num_subqueries
        assert params[7] is True  # has_group_by
        assert params[8] is True  # has_order_by

    def test_empty_sql_returns_none(self):
        """Empty SQL returns None without DB call."""
        result = query_features.compute_and_store(1, "")
        assert result is None

    def test_unparseable_sql_returns_none(self):
        """Unparseable SQL returns None without DB call."""
        result = query_features.compute_and_store(1, "NOT VALID SQL ???")
        assert result is None


# ---------------------------------------------------------------------------
# compute_and_store_batch
# ---------------------------------------------------------------------------


class TestComputeAndStoreBatch:
    @patch("query_features.db.fetch_one")
    def test_batch_processes_all(self, mock_fetch_one):
        """Batch processes all valid queries."""
        mock_fetch_one.return_value = _qf_row()

        rows = [
            (1, "SELECT a FROM t1"),
            (2, "SELECT b FROM t2"),
            (3, "SELECT c FROM t3"),
        ]
        count = query_features.compute_and_store_batch(rows)

        assert count == 3
        assert mock_fetch_one.call_count == 3

    @patch("query_features.db.fetch_one")
    def test_batch_skips_invalid(self, mock_fetch_one):
        """Batch skips invalid SQL and counts only successes."""
        mock_fetch_one.return_value = _qf_row()

        rows = [
            (1, "SELECT a FROM t1"),
            (2, ""),  # empty — will fail
            (3, "SELECT c FROM t3"),
        ]
        count = query_features.compute_and_store_batch(rows)

        assert count == 2
        assert mock_fetch_one.call_count == 2

    def test_empty_batch(self):
        """Empty batch returns 0."""
        count = query_features.compute_and_store_batch([])
        assert count == 0


# ---------------------------------------------------------------------------
# update_table_metadata
# ---------------------------------------------------------------------------


class TestUpdateTableMetadata:
    @patch("query_features.db.execute")
    @patch("query_features.db.fetch_all")
    def test_updates_sizes(self, mock_fetch_all, mock_execute):
        """Updates max_table_size_bytes and total_data_bytes from catalog sizes."""
        mock_fetch_all.return_value = [
            {"query_id": 1, "tables": ["cat.sch.t1", "cat.sch.t2"]},
            {"query_id": 2, "tables": ["cat.sch.t1"]},
        ]

        metadata = {
            "cat.sch.t1": 1_000_000,
            "cat.sch.t2": 5_000_000,
        }
        updated = query_features.update_table_metadata([1, 2], metadata)

        assert updated == 2
        assert mock_execute.call_count == 2

        # Query 1: max=5M, total=6M
        args1 = mock_execute.call_args_list[0][0][1]
        assert args1[0] == 5_000_000  # max
        assert args1[1] == 6_000_000  # total
        assert args1[2] == 1  # query_id

        # Query 2: max=1M, total=1M
        args2 = mock_execute.call_args_list[1][0][1]
        assert args2[0] == 1_000_000  # max
        assert args2[1] == 1_000_000  # total
        assert args2[2] == 2  # query_id

    def test_empty_query_ids(self):
        """Returns 0 when no query_ids provided."""
        assert query_features.update_table_metadata([], {"t": 100}) == 0

    def test_empty_metadata(self):
        """Returns 0 when no metadata provided."""
        assert query_features.update_table_metadata([1, 2], {}) == 0

    @patch("query_features.db.execute")
    @patch("query_features.db.fetch_all")
    def test_unknown_tables_default_to_zero(self, mock_fetch_all, mock_execute):
        """Tables not in metadata map get size 0."""
        mock_fetch_all.return_value = [
            {"query_id": 1, "tables": ["cat.sch.unknown"]},
        ]

        updated = query_features.update_table_metadata([1], {"cat.sch.other": 500})

        assert updated == 1
        args = mock_execute.call_args[0][1]
        assert args[0] == 0  # max (unknown table)
        assert args[1] == 0  # total


# ---------------------------------------------------------------------------
# backfill_all
# ---------------------------------------------------------------------------


class TestBackfillAll:
    @patch("query_features.compute_and_store")
    @patch("query_features.db.fetch_all")
    def test_backfills_missing(self, mock_fetch_all, mock_compute):
        """Backfills queries that have no features row."""
        mock_fetch_all.return_value = [
            {"query_id": 10, "query_text": "SELECT a FROM t1"},
            {"query_id": 11, "query_text": "SELECT b FROM t2"},
        ]
        mock_compute.return_value = _qf_row()

        result = query_features.backfill_all()

        assert result == {"total": 2, "computed": 2, "skipped": 0}
        assert mock_compute.call_count == 2

    @patch("query_features.compute_and_store")
    @patch("query_features.db.fetch_all")
    def test_reports_skipped(self, mock_fetch_all, mock_compute):
        """Counts queries that failed to parse as skipped."""
        mock_fetch_all.return_value = [
            {"query_id": 10, "query_text": "SELECT a FROM t1"},
            {"query_id": 11, "query_text": "INVALID SQL"},
        ]
        mock_compute.side_effect = [_qf_row(), None]

        result = query_features.backfill_all()

        assert result == {"total": 2, "computed": 1, "skipped": 1}

    @patch("query_features.db.fetch_all")
    def test_nothing_to_backfill(self, mock_fetch_all):
        """Returns zeros when all queries already have features."""
        mock_fetch_all.return_value = []

        result = query_features.backfill_all()

        assert result == {"total": 0, "computed": 0, "skipped": 0}
