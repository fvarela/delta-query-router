"""Integration tests for benchmark execution with ephemeral Databricks warehouses.

Tests the modified _run_benchmark_inner() flow to verify:
- Ephemeral warehouse creation for engines without a warehouse_id
- Skipping ephemeral creation for engines WITH a warehouse_id
- Cleanup in finally block (success and failure cases)
- Graceful failures when warehouse creation or startup fails
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

import benchmarks_api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _query_row(id=1, collection_id=1, seq=1, sql="SELECT 1"):
    return {
        "id": id,
        "collection_id": collection_id,
        "query_text": sql,
        "sequence_number": seq,
    }


def _definition_row(id=1, collection_id=1, engine_id="databricks-serverless-xs"):
    return {
        "id": id,
        "collection_id": collection_id,
        "engine_id": engine_id,
        "created_at": _NOW,
    }


def _run_row(id=1, definition_id=1, status="pending"):
    return {
        "id": id,
        "definition_id": definition_id,
        "status": status,
        "error_message": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _databricks_engine_no_wh(id="databricks-serverless-xs"):
    """Databricks engine WITHOUT warehouse_id in config (triggers ephemeral)."""
    return {
        "id": id,
        "engine_type": "databricks_sql",
        "display_name": f"Databricks {id}",
        "config": {
            "cluster_size": "X-Small",
            "is_serverless": True,
            "has_photon": True,
        },
        "k8s_service_name": None,
        "cost_tier": 6,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _databricks_engine_with_wh(id="databricks-synced", warehouse_id="wh-existing"):
    """Databricks engine WITH warehouse_id in config (skips ephemeral)."""
    return {
        "id": id,
        "engine_type": "databricks_sql",
        "display_name": f"Databricks {id}",
        "config": {
            "cluster_size": "X-Small",
            "is_serverless": True,
            "has_photon": True,
            "warehouse_id": warehouse_id,
        },
        "k8s_service_name": None,
        "cost_tier": 6,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _duckdb_engine(id="duckdb-1"):
    """DuckDB engine (never triggers ephemeral warehouse)."""
    return {
        "id": id,
        "engine_type": "duckdb",
        "display_name": "DuckDB Small",
        "config": {"memory_gb": 2, "cpu_count": 2},
        "k8s_service_name": "duckdb-worker-small",
        "cost_tier": 3,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEphemeralWarehouseCreation:
    """Verify ephemeral warehouse is created for Databricks engines without warehouse_id."""

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_databricks", return_value=500.0)
    @patch("benchmarks_api._execute_query_on_databricks")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_creates_ephemeral_for_engine_without_warehouse_id(
        self, mock_snapshot, mock_exec, mock_run_query, mock_warmup, mock_eph
    ):
        mock_run_query.return_value = {
            "execution_time_ms": 100.0,
            "error_message": None,
        }
        mock_eph.create_for_benchmark.return_value = "wh-ephemeral-42"
        mock_eph.wait_for_running.return_value = True

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=42)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host="https://db.example.com",
            databricks_token="tok",
        )

        mock_eph.create_for_benchmark.assert_called_once_with(ws, "X-Small", 42)
        mock_eph.wait_for_running.assert_called_once_with(ws, "wh-ephemeral-42")
        # Warmup and execution should use the ephemeral warehouse
        mock_warmup.assert_called_once()
        assert mock_warmup.call_args[0][1] == "wh-ephemeral-42"
        mock_run_query.assert_called_once()
        assert mock_run_query.call_args[0][1] == "wh-ephemeral-42"
        # Cleanup must happen
        mock_eph.delete_warehouse.assert_called_once_with(ws, "wh-ephemeral-42")

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_databricks", return_value=200.0)
    @patch("benchmarks_api._execute_query_on_databricks")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_skips_ephemeral_for_engine_with_warehouse_id(
        self, mock_snapshot, mock_exec, mock_run_query, mock_warmup, mock_eph
    ):
        mock_run_query.return_value = {"execution_time_ms": 50.0, "error_message": None}

        eid = "databricks-synced"
        runs = {
            eid: {"definition": _definition_row(engine_id=eid), "run": _run_row(id=10)}
        }
        engines = {eid: _databricks_engine_with_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host="https://db.example.com",
            databricks_token="tok",
        )

        # No ephemeral creation
        mock_eph.create_for_benchmark.assert_not_called()
        mock_eph.wait_for_running.assert_not_called()
        mock_eph.delete_warehouse.assert_not_called()
        # Warmup should use the engine's own warehouse_id
        mock_warmup.assert_called_once()
        assert mock_warmup.call_args[0][1] == "wh-existing"

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_databricks", return_value=100.0)
    @patch("benchmarks_api._execute_query_on_databricks")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_falls_back_to_global_warehouse_id(
        self, mock_snapshot, mock_exec, mock_run_query, mock_warmup, mock_eph
    ):
        """Engine has no warehouse_id in config but global warehouse_id is set."""
        mock_run_query.return_value = {"execution_time_ms": 80.0, "error_message": None}

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=5)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id="wh-global-123",
            databricks_host="https://db.example.com",
            databricks_token="tok",
        )

        # Global warehouse available — no ephemeral needed
        mock_eph.create_for_benchmark.assert_not_called()
        mock_warmup.assert_called_once()
        assert mock_warmup.call_args[0][1] == "wh-global-123"


class TestEphemeralWarehouseCleanup:
    """Verify ephemeral warehouse is always cleaned up, even on failure."""

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_databricks", side_effect=Exception("Warmup crashed"))
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_deleted_on_warmup_failure(
        self, mock_snapshot, mock_exec, mock_warmup, mock_eph
    ):
        mock_eph.create_for_benchmark.return_value = "wh-eph-99"
        mock_eph.wait_for_running.return_value = True

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=99)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Warehouse should still be cleaned up despite warmup failure
        mock_eph.delete_warehouse.assert_called_once_with(ws, "wh-eph-99")

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_databricks", return_value=300.0)
    @patch("benchmarks_api._execute_query_on_databricks")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_deleted_on_query_execution_failure(
        self, mock_snapshot, mock_exec, mock_run_query, mock_warmup, mock_eph
    ):
        mock_run_query.side_effect = Exception("Query exploded")
        mock_eph.create_for_benchmark.return_value = "wh-eph-77"
        mock_eph.wait_for_running.return_value = True

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=77)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        mock_eph.delete_warehouse.assert_called_once_with(ws, "wh-eph-77")


class TestEphemeralWarehouseStartupFailure:
    """Verify graceful handling when warehouse creation or startup fails."""

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_creation_failure_marks_run_failed(
        self, mock_snapshot, mock_exec, mock_eph
    ):
        mock_eph.create_for_benchmark.side_effect = RuntimeError("API quota exceeded")

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=33)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        # Should not raise — error is caught and run is marked failed
        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Run should be marked as failed
        exec_strs = [str(c) for c in mock_exec.call_args_list]
        assert any("failed" in s for s in exec_strs)

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_startup_timeout_marks_run_failed_and_cleans_up(
        self, mock_snapshot, mock_exec, mock_eph
    ):
        mock_eph.create_for_benchmark.return_value = "wh-eph-slow"
        mock_eph.wait_for_running.return_value = False  # Timeout

        eid = "databricks-serverless-xs"
        runs = {eid: {"definition": _definition_row(), "run": _run_row(id=44)}}
        engines = {eid: _databricks_engine_no_wh()}
        ws = MagicMock()

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=ws,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Run should be marked as failed
        exec_strs = [str(c) for c in mock_exec.call_args_list]
        assert any("failed" in s and "timeout" in s.lower() for s in exec_strs)
        # Warehouse should be cleaned up
        mock_eph.delete_warehouse.assert_called_with(ws, "wh-eph-slow")


class TestDuckdbEngineUnaffected:
    """Verify DuckDB engine path is completely unaffected by ephemeral logic."""

    @patch("benchmarks_api.ephemeral_warehouses")
    @patch("benchmarks_api._warmup_duckdb_sync", return_value=30.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api._snapshot_table_metadata")
    def test_duckdb_never_triggers_ephemeral(
        self, mock_snapshot, mock_exec, mock_run_query, mock_warmup, mock_eph
    ):
        mock_run_query.return_value = {"execution_time_ms": 5.0, "error_message": None}

        eid = "duckdb-1"
        runs = {
            eid: {"definition": _definition_row(engine_id=eid), "run": _run_row(id=1)}
        }
        engines = {eid: _duckdb_engine()}

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        mock_eph.create_for_benchmark.assert_not_called()
        mock_eph.wait_for_running.assert_not_called()
        mock_eph.delete_warehouse.assert_not_called()
        mock_warmup.assert_called_once()
        mock_run_query.assert_called_once()
