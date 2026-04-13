"""Tests for benchmarks_api.py — benchmark definitions + runs CRUD and execution."""

import time
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import auth
import benchmarks_api
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-benchmarks"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


_NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _collection_row(id=1):
    return {
        "id": id,
        "name": "Test Collection",
        "description": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _query_row(id=1, collection_id=1, seq=1, sql="SELECT 1"):
    return {
        "id": id,
        "collection_id": collection_id,
        "query_text": sql,
        "sequence_number": seq,
    }


def _engine_row(id="duckdb-1", engine_type="duckdb", active=True):
    return {
        "id": id,
        "engine_type": engine_type,
        "display_name": f"Engine {id}",
        "config": {},
        "k8s_service_name": "duckdb-worker" if engine_type == "duckdb" else None,
        "cost_tier": 3,
        "is_active": active,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _definition_row(id=1, collection_id=1, engine_id="duckdb-1"):
    return {
        "id": id,
        "collection_id": collection_id,
        "engine_id": engine_id,
        "created_at": _NOW,
    }


def _run_row(id=1, definition_id=1, status="warming_up"):
    return {
        "id": id,
        "definition_id": definition_id,
        "status": status,
        "error_message": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ---------------------------------------------------------------------------
# POST /api/benchmarks — creation (now async, returns 202)
# ---------------------------------------------------------------------------


class TestCreateBenchmark:
    """POST /api/benchmarks — validates inputs and returns 202 with run_ids."""

    def test_requires_auth(self):
        resp = client.post(
            "/api/benchmarks", json={"collection_id": 1, "engine_ids": ["duckdb-1"]}
        )
        assert resp.status_code == 401

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_collection_not_found(self, mock_fetch):
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 999, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 404
        assert "Collection" in resp.json()["detail"]

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    @patch("benchmarks_api.db.fetch_one", return_value=_collection_row())
    def test_empty_collection(self, mock_one, mock_all):
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "no queries" in resp.json()["detail"].lower()

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_engine_not_found(self, mock_one, mock_all):
        mock_one.side_effect = [_collection_row(), None]
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["nonexistent"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 404
        assert "Engine" in resp.json()["detail"]

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_engine_not_active(self, mock_one, mock_all):
        mock_one.side_effect = [_collection_row(), _engine_row(active=False)]
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "not active" in resp.json()["detail"].lower()

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_no_engines(self, mock_one, mock_all):
        mock_one.return_value = _collection_row()
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "No engines" in resp.json()["detail"]

    @patch("benchmarks_api._run_benchmark_thread")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_returns_202_with_run_ids(self, mock_one, mock_all, mock_thread):
        """Endpoint returns 202 immediately with run_ids and status 'started'."""
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _definition_row(id=10),
            _run_row(id=42, definition_id=10, status="pending"),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 202
        data = resp.json()
        assert data["run_ids"] == [42]
        assert data["status"] == "started"

    @patch("benchmarks_api._run_benchmark_thread")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_multiple_engines_returns_multiple_run_ids(
        self, mock_one, mock_all, mock_thread
    ):
        """2 engines → 2 run_ids returned."""
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(id="duckdb-1"),
            _engine_row(id="duckdb-2"),
            _definition_row(id=1, engine_id="duckdb-1"),
            _run_row(id=90, definition_id=1, status="pending"),
            _definition_row(id=2, engine_id="duckdb-2"),
            _run_row(id=91, definition_id=2, status="pending"),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1", "duckdb-2"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "started"
        assert len(data["run_ids"]) == 2
        assert 90 in data["run_ids"]
        assert 91 in data["run_ids"]

    @patch("benchmarks_api._benchmark_lock")
    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_concurrent_benchmark_rejected(self, mock_one, mock_all, mock_lock):
        """409 if a benchmark is already running."""
        mock_lock.locked.return_value = True
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
        ]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Background thread execution
# ---------------------------------------------------------------------------


class TestRunBenchmarkInner:
    """_run_benchmark_inner — core execution logic."""

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=50.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    def test_single_engine_success(self, mock_exec, mock_run_query, mock_warmup):
        """1 engine, 1 query → warmup + running + complete."""
        mock_run_query.return_value = {"execution_time_ms": 12.5, "error_message": None}

        runs = {"duckdb-1": {"definition": _definition_row(), "run": _run_row(id=42)}}
        engines = {"duckdb-1": _engine_row()}
        queries = [_query_row()]

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            queries,
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        mock_warmup.assert_called_once()
        mock_run_query.assert_called_once()

        # Check SQL strings and parameters together
        exec_calls = mock_exec.call_args_list
        exec_strs = [str(c) for c in exec_calls]
        assert any("warming_up" in s for s in exec_strs)
        assert any("benchmark_engine_warmups" in s for s in exec_strs)
        assert any("running" in s for s in exec_strs)
        assert any("benchmark_results" in s for s in exec_strs)
        assert any("complete" in s for s in exec_strs)

    @patch(
        "benchmarks_api._warmup_duckdb_sync",
        side_effect=Exception("Connection refused"),
    )
    @patch("benchmarks_api.db.execute")
    def test_warmup_failure_marks_failed_continues(self, mock_exec, mock_warmup):
        """Warmup failure → run marked 'failed', next engine still runs."""
        runs = {
            "duckdb-1": {"definition": _definition_row(id=1), "run": _run_row(id=10)},
            "duckdb-2": {"definition": _definition_row(id=2), "run": _run_row(id=11)},
        }
        engines = {
            "duckdb-1": _engine_row(id="duckdb-1"),
            "duckdb-2": _engine_row(id="duckdb-2"),
        }

        with (
            patch("benchmarks_api._warmup_duckdb_sync") as mock_w,
            patch("benchmarks_api._execute_query_on_duckdb_sync") as mock_q,
        ):
            # First engine warmup fails, second succeeds
            mock_w.side_effect = [Exception("Connection refused"), 30.0]
            mock_q.return_value = {"execution_time_ms": 5.0, "error_message": None}

            benchmarks_api._run_benchmark_inner(
                runs,
                engines,
                [_query_row()],
                workspace_client=None,
                warehouse_id=None,
                databricks_host=None,
                databricks_token=None,
            )

        # Check that first run was marked failed and second was completed
        exec_calls = mock_exec.call_args_list
        exec_sqls = [c[0][0] for c in exec_calls]
        failed_calls = [c for c in exec_calls if "failed" in str(c)]
        complete_calls = [c for c in exec_calls if "'complete'" in str(c)]
        assert len(failed_calls) >= 1
        assert len(complete_calls) >= 1

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=20.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    def test_all_queries_fail_marks_failed(
        self, mock_exec, mock_run_query, mock_warmup
    ):
        """If all queries fail, run status is 'failed'."""
        mock_run_query.return_value = {
            "execution_time_ms": 1.0,
            "error_message": "Parse error",
        }

        runs = {"duckdb-1": {"definition": _definition_row(), "run": _run_row(id=42)}}
        engines = {"duckdb-1": _engine_row()}

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        exec_calls = mock_exec.call_args_list
        failed_calls = [c for c in exec_calls if "'failed'" in str(c)]
        assert len(failed_calls) >= 1

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=20.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    def test_partial_query_failure_marks_complete_with_error_count(
        self, mock_exec, mock_run_query, mock_warmup
    ):
        """1/2 queries fail → status is 'complete' (not all failed) with error message."""
        queries = [
            _query_row(id=1, seq=1),
            _query_row(id=2, seq=2),
        ]
        mock_run_query.side_effect = [
            {"execution_time_ms": 5.0, "error_message": None},
            {"execution_time_ms": 1.0, "error_message": "Parser Error"},
        ]

        runs = {"duckdb-1": {"definition": _definition_row(), "run": _run_row(id=7)}}
        engines = {"duckdb-1": _engine_row()}

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            queries,
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Both results inserted
        result_inserts = [
            c for c in mock_exec.call_args_list if "benchmark_results" in c[0][0]
        ]
        assert len(result_inserts) == 2

        # Status should be 'complete' (not all failed)
        complete_calls = [c for c in mock_exec.call_args_list if "'complete'" in str(c)]
        assert len(complete_calls) >= 1

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=10.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    def test_two_engines_sequential(self, mock_exec, mock_run_query, mock_warmup):
        """2 engines run sequentially: each gets warmup + queries + status updates."""
        mock_run_query.return_value = {"execution_time_ms": 8.0, "error_message": None}

        runs = {
            "duckdb-1": {
                "definition": _definition_row(id=1, engine_id="duckdb-1"),
                "run": _run_row(id=90, definition_id=1),
            },
            "duckdb-2": {
                "definition": _definition_row(id=2, engine_id="duckdb-2"),
                "run": _run_row(id=91, definition_id=2),
            },
        }
        engines = {
            "duckdb-1": _engine_row(id="duckdb-1"),
            "duckdb-2": _engine_row(id="duckdb-2"),
        }

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        assert mock_warmup.call_count == 2
        assert mock_run_query.call_count == 2


# ---------------------------------------------------------------------------
# GET /api/benchmarks/runs/{run_id}/progress
# ---------------------------------------------------------------------------


class TestRunProgress:
    """GET /api/benchmarks/runs/{run_id}/progress — live progress polling."""

    @patch("benchmarks_api.db.fetch_one")
    def test_progress_running(self, mock_one):
        """Returns progress for a running benchmark."""
        mock_one.side_effect = [
            # run query
            {
                "run_id": 42,
                "definition_id": 10,
                "status": "running",
                "created_at": _NOW,
                "updated_at": _NOW,
                "error_message": None,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "TPC-DS SF1",
                "engine_display_name": "DuckDB — Small",
            },
            # total_queries
            {"cnt": 99},
            # completed
            {"cnt": 23},
            # failed
            {"cnt": 1},
        ]

        resp = client.get("/api/benchmarks/runs/42/progress", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 42
        assert data["status"] == "running"
        assert data["total_queries"] == 99
        assert data["completed_queries"] == 23
        assert data["failed_queries"] == 1
        assert data["engine_display_name"] == "DuckDB — Small"
        assert data["elapsed_ms"] > 0

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_progress_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/runs/999/progress", headers=_auth_header())
        assert resp.status_code == 404

    def test_progress_requires_auth(self):
        resp = client.get("/api/benchmarks/runs/1/progress")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/active
# ---------------------------------------------------------------------------


class TestActiveBenchmarks:
    """GET /api/benchmarks/active — detect in-progress benchmarks."""

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_no_active(self, mock_all):
        resp = client.get("/api/benchmarks/active", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("benchmarks_api.db.fetch_all")
    def test_returns_active_runs(self, mock_all):
        mock_all.return_value = [
            {
                "run_id": 10,
                "definition_id": 5,
                "status": "running",
                "created_at": _NOW,
                "updated_at": _NOW,
                "error_message": None,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "TPC-DS",
                "engine_display_name": "DuckDB Small",
                "total_queries": 99,
                "completed_queries": 50,
                "failed_queries": 2,
            },
        ]
        resp = client.get("/api/benchmarks/active", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["run_id"] == 10
        assert data[0]["status"] == "running"

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/active")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks — list definitions
# ---------------------------------------------------------------------------


class TestListDefinitions:
    """GET /api/benchmarks — list benchmark definitions."""

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_list_empty(self, mock_all):
        resp = client.get("/api/benchmarks", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("benchmarks_api.db.fetch_one", return_value=None)  # no latest_run
    @patch("benchmarks_api.db.fetch_all")
    def test_list_returns_definitions(self, mock_all, mock_one):
        mock_all.return_value = [
            {
                "id": 1,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "C1",
                "engine_display_name": "DuckDB Small",
                "run_count": 3,
                "created_at": _NOW,
            },
        ]
        resp = client.get("/api/benchmarks", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["collection_name"] == "C1"
        assert data[0]["run_count"] == 3
        assert data[0]["latest_run"] is None

    @patch("benchmarks_api.db.fetch_one")
    @patch("benchmarks_api.db.fetch_all")
    def test_list_with_latest_run(self, mock_all, mock_one):
        mock_all.return_value = [
            {
                "id": 1,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "C1",
                "engine_display_name": "DuckDB Small",
                "run_count": 1,
                "created_at": _NOW,
            },
        ]
        mock_one.return_value = _run_row(id=5, definition_id=1, status="complete")
        resp = client.get("/api/benchmarks", headers=_auth_header())
        data = resp.json()
        assert data[0]["latest_run"]["id"] == 5
        assert data[0]["latest_run"]["status"] == "complete"

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_filter_by_collection_id(self, mock_all):
        resp = client.get("/api/benchmarks?collection_id=5", headers=_auth_header())
        assert resp.status_code == 200
        sql = mock_all.call_args[0][0]
        assert "collection_id" in sql

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_filter_by_engine_id(self, mock_all):
        resp = client.get("/api/benchmarks?engine_id=duckdb-1", headers=_auth_header())
        assert resp.status_code == 200
        sql = mock_all.call_args[0][0]
        assert "engine_id" in sql

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id} — definition detail
# ---------------------------------------------------------------------------


class TestGetDefinition:
    """GET /api/benchmarks/{id} — definition with runs."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_get_with_runs(self, mock_one, mock_all):
        mock_one.return_value = {
            "id": 1,
            "collection_id": 1,
            "engine_id": "duckdb-1",
            "collection_name": "Test",
            "engine_display_name": "DuckDB Small",
            "created_at": _NOW,
        }
        mock_all.return_value = [
            _run_row(id=10, definition_id=1, status="complete"),
            _run_row(id=11, definition_id=1, status="running"),
        ]

        resp = client.get("/api/benchmarks/1", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["collection_name"] == "Test"
        assert data["run_count"] == 2
        assert len(data["runs"]) == 2

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id}/runs — list runs
# ---------------------------------------------------------------------------


class TestListRuns:
    """GET /api/benchmarks/{id}/runs — runs for a definition."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_list_runs(self, mock_one, mock_all):
        mock_one.return_value = _definition_row(id=1)
        mock_all.return_value = [
            _run_row(id=10, definition_id=1, status="complete"),
        ]
        resp = client.get("/api/benchmarks/1/runs", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 10

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_definition_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/999/runs", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/1/runs")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id}/runs/{run_id} — run detail
# ---------------------------------------------------------------------------


class TestGetRun:
    """GET /api/benchmarks/{id}/runs/{run_id} — run with warmups and results."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_get_run_detail(self, mock_one, mock_all):
        mock_one.return_value = _run_row(id=10, definition_id=1, status="complete")
        mock_all.side_effect = [
            # warmups
            [
                {
                    "id": 1,
                    "run_id": 10,
                    "engine_id": "duckdb-1",
                    "engine_display_name": "DuckDB Small",
                    "cold_start_time_ms": 50.0,
                    "started_at": _NOW,
                }
            ],
            # results
            [
                {
                    "id": 1,
                    "run_id": 10,
                    "engine_id": "duckdb-1",
                    "engine_display_name": "DuckDB Small",
                    "query_id": 1,
                    "query_text": "SELECT 1",
                    "sequence_number": 1,
                    "execution_time_ms": 12.0,
                    "error_message": None,
                }
            ],
        ]

        resp = client.get("/api/benchmarks/1/runs/10", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert len(data["warmups"]) == 1
        assert data["warmups"][0]["cold_start_time_ms"] == 50.0
        assert len(data["results"]) == 1
        assert data["results"][0]["execution_time_ms"] == 12.0

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_run_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/1/runs/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/1/runs/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/benchmarks/{id} — delete definition
# ---------------------------------------------------------------------------


class TestDeleteDefinition:
    """DELETE /api/benchmarks/{id} — cascade delete definition."""

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_delete_existing(self, mock_one, mock_exec):
        mock_one.return_value = _definition_row(id=5)
        resp = client.delete("/api/benchmarks/5", headers=_auth_header())
        assert resp.status_code == 204
        mock_exec.assert_called_once()

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_delete_not_found(self, mock_one):
        resp = client.delete("/api/benchmarks/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.delete("/api/benchmarks/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/benchmarks/{id}/runs/{run_id} — delete single run
# ---------------------------------------------------------------------------


class TestDeleteRun:
    """DELETE /api/benchmarks/{id}/runs/{run_id} — cascade delete run."""

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_delete_existing(self, mock_one, mock_exec):
        mock_one.return_value = _run_row(id=10, definition_id=1)
        resp = client.delete("/api/benchmarks/1/runs/10", headers=_auth_header())
        assert resp.status_code == 204
        mock_exec.assert_called_once()

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_delete_not_found(self, mock_one):
        resp = client.delete("/api/benchmarks/1/runs/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.delete("/api/benchmarks/1/runs/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Internal helper unit tests
# ---------------------------------------------------------------------------


class TestExecuteQueryOnDuckdbSync:
    """_execute_query_on_duckdb_sync — targeted DuckDB execution."""

    def test_success(self):
        engine = _engine_row()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": ["1"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 3.5,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("benchmarks_api.httpx.Client", return_value=mock_client):
            result = benchmarks_api._execute_query_on_duckdb_sync(engine, "SELECT 1")

        assert result["execution_time_ms"] == 3.5
        assert result["error_message"] is None

    def test_http_error(self):
        engine = _engine_row()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad query"
        mock_resp.json.return_value = {"detail": "Parser Error"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("benchmarks_api.httpx.Client", return_value=mock_client):
            result = benchmarks_api._execute_query_on_duckdb_sync(engine, "BAD SQL")

        assert result["error_message"] is not None
        assert "Parser Error" in result["error_message"]

    def test_connection_error(self):
        engine = _engine_row()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("Connection refused")

        with patch("benchmarks_api.httpx.Client", return_value=mock_client):
            result = benchmarks_api._execute_query_on_duckdb_sync(engine, "SELECT 1")

        assert result["error_message"] is not None
        assert "Connection refused" in result["error_message"]


# ---------------------------------------------------------------------------
# _get_or_create_definition unit tests
# ---------------------------------------------------------------------------


class TestGetOrCreateDefinition:
    """_get_or_create_definition — upsert logic."""

    @patch("benchmarks_api.db.fetch_one")
    def test_existing_returned(self, mock_one):
        existing = _definition_row(id=5, collection_id=1, engine_id="duckdb-1")
        mock_one.return_value = existing
        result = benchmarks_api._get_or_create_definition(1, "duckdb-1")
        assert result["id"] == 5
        assert mock_one.call_count == 1

    @patch("benchmarks_api.db.fetch_one")
    def test_created_when_missing(self, mock_one):
        new_row = _definition_row(id=10, collection_id=2, engine_id="duckdb-2")
        mock_one.side_effect = [None, new_row]
        result = benchmarks_api._get_or_create_definition(2, "duckdb-2")
        assert result["id"] == 10
        assert mock_one.call_count == 2


# ---------------------------------------------------------------------------
# POST /api/benchmarks/runs/{run_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelRun:
    """POST /api/benchmarks/runs/{run_id}/cancel — per-engine cancellation."""

    @patch("benchmarks_api.db.fetch_one")
    def test_cancel_running_run(self, mock_one):
        """Cancelling a running run returns cancel_requested and adds to set."""
        mock_one.return_value = {"id": 42, "status": "running"}
        benchmarks_api._cancelled_run_ids.discard(42)  # ensure clean state

        resp = client.post("/api/benchmarks/runs/42/cancel", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 42
        assert data["status"] == "cancel_requested"
        assert 42 in benchmarks_api._cancelled_run_ids

        # Clean up
        benchmarks_api._cancelled_run_ids.discard(42)

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_cancel_pending_run(self, mock_one, mock_exec):
        """Cancelling a pending run marks it cancelled immediately in DB."""
        mock_one.return_value = {"id": 10, "status": "pending"}
        benchmarks_api._cancelled_run_ids.discard(10)

        resp = client.post("/api/benchmarks/runs/10/cancel", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 10
        assert data["status"] == "cancelled"
        # Should have updated DB directly with status='cancelled'
        mock_exec.assert_called_once()
        call_sql = mock_exec.call_args[0][0]
        assert "cancelled" in call_sql
        assert "Skipped" in call_sql
        # Also adds to cancellation set (so background thread skips too)
        assert 10 in benchmarks_api._cancelled_run_ids
        benchmarks_api._cancelled_run_ids.discard(10)

    @patch("benchmarks_api.db.fetch_one")
    def test_cancel_warming_up_run(self, mock_one):
        """Can cancel a warming_up run."""
        mock_one.return_value = {"id": 11, "status": "warming_up"}
        resp = client.post("/api/benchmarks/runs/11/cancel", headers=_auth_header())
        assert resp.status_code == 200
        benchmarks_api._cancelled_run_ids.discard(11)

    @patch("benchmarks_api.db.fetch_one")
    def test_cancel_complete_rejected(self, mock_one):
        """Cannot cancel an already-complete run."""
        mock_one.return_value = {"id": 42, "status": "complete"}
        resp = client.post("/api/benchmarks/runs/42/cancel", headers=_auth_header())
        assert resp.status_code == 400
        assert "Cannot cancel" in resp.json()["detail"]

    @patch("benchmarks_api.db.fetch_one")
    def test_cancel_failed_rejected(self, mock_one):
        """Cannot cancel an already-failed run."""
        mock_one.return_value = {"id": 42, "status": "failed"}
        resp = client.post("/api/benchmarks/runs/42/cancel", headers=_auth_header())
        assert resp.status_code == 400

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_cancel_not_found(self, mock_one):
        resp = client.post("/api/benchmarks/runs/999/cancel", headers=_auth_header())
        assert resp.status_code == 404

    def test_cancel_requires_auth(self):
        resp = client.post("/api/benchmarks/runs/1/cancel")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cancellation in _run_benchmark_inner
# ---------------------------------------------------------------------------


class TestCancellationInRunner:
    """_run_benchmark_inner respects _cancelled_run_ids between queries."""

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=10.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_cancellation_stops_queries(
        self, mock_fetch_one, mock_exec, mock_run_query, mock_warmup
    ):
        """Run is cancelled between queries — remaining queries skipped, status='cancelled'."""
        # fetch_one called for the cancelled-query count
        mock_fetch_one.return_value = {"cnt": 1}
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # After first query succeeds, add run_id to cancelled set
                benchmarks_api._cancelled_run_ids.add(42)
            return {"execution_time_ms": 5.0, "error_message": None}

        mock_run_query.side_effect = side_effect

        runs = {"duckdb-1": {"definition": _definition_row(), "run": _run_row(id=42)}}
        engines = {"duckdb-1": _engine_row()}
        queries = [
            _query_row(id=1, seq=1),
            _query_row(id=2, seq=2),
            _query_row(id=3, seq=3),
        ]

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            queries,
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Only 1 query executed (cancelled before 2nd)
        assert mock_run_query.call_count == 1
        # Status should be 'cancelled'
        exec_calls = [str(c) for c in mock_exec.call_args_list]
        assert any("cancelled" in s.lower() for s in exec_calls)

    @patch("benchmarks_api._warmup_duckdb_sync", return_value=10.0)
    @patch("benchmarks_api._execute_query_on_duckdb_sync")
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_cancellation_before_execution(
        self, mock_fetch_one, mock_exec, mock_run_query, mock_warmup
    ):
        """Run cancelled during warmup — skip execution entirely, status='cancelled'."""
        runs = {"duckdb-1": {"definition": _definition_row(), "run": _run_row(id=50)}}
        engines = {"duckdb-1": _engine_row()}

        # Pre-cancel
        benchmarks_api._cancelled_run_ids.add(50)

        benchmarks_api._run_benchmark_inner(
            runs,
            engines,
            [_query_row()],
            workspace_client=None,
            warehouse_id=None,
            databricks_host=None,
            databricks_token=None,
        )

        # Warmup happens (cancel check is after warmup), but since our cancel check
        # is BEFORE running phase, no queries should execute
        assert mock_run_query.call_count == 0
        exec_calls = [str(c) for c in mock_exec.call_args_list]
        assert any("cancelled" in s.lower() for s in exec_calls)

        # Clean up
        benchmarks_api._cancelled_run_ids.discard(50)


# ---------------------------------------------------------------------------
# GET /api/benchmarks/runs/{run_id}/results — incremental results
# ---------------------------------------------------------------------------


class TestRunResults:
    """GET /api/benchmarks/runs/{run_id}/results — per-query results feed."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_all_results(self, mock_one, mock_all):
        """Returns all results when since=0 (default)."""
        mock_one.return_value = {"id": 42}
        mock_all.return_value = [
            {
                "result_id": 1,
                "engine_id": "duckdb-1",
                "query_id": 10,
                "sequence_number": 1,
                "execution_time_ms": 45.0,
                "error_message": None,
            },
            {
                "result_id": 2,
                "engine_id": "duckdb-1",
                "query_id": 11,
                "sequence_number": 2,
                "execution_time_ms": 120.0,
                "error_message": None,
            },
        ]

        resp = client.get("/api/benchmarks/runs/42/results", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["result_id"] == 1
        assert data[0]["sequence_number"] == 1
        assert data[0]["execution_time_ms"] == 45.0

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_incremental_since(self, mock_one, mock_all):
        """With since=5, only returns results with id > 5."""
        mock_one.return_value = {"id": 42}
        mock_all.return_value = [
            {
                "result_id": 6,
                "engine_id": "duckdb-1",
                "query_id": 15,
                "sequence_number": 6,
                "execution_time_ms": 80.0,
                "error_message": None,
            },
        ]

        resp = client.get(
            "/api/benchmarks/runs/42/results?since=5", headers=_auth_header()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["result_id"] == 6

        # Verify the SQL was called with since=5
        sql_call = mock_all.call_args[0]
        assert sql_call[1] == (42, 5)

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_error_message_truncated(self, mock_one, mock_all):
        """Error messages are truncated to 120 chars."""
        mock_one.return_value = {"id": 42}
        long_error = "X" * 200
        mock_all.return_value = [
            {
                "result_id": 1,
                "engine_id": "duckdb-1",
                "query_id": 10,
                "sequence_number": 1,
                "execution_time_ms": 1.0,
                "error_message": long_error,
            },
        ]

        resp = client.get("/api/benchmarks/runs/42/results", headers=_auth_header())
        data = resp.json()
        assert len(data[0]["error_message"]) == 120

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    @patch("benchmarks_api.db.fetch_one")
    def test_empty_results(self, mock_one, mock_all):
        """Returns empty list when no results yet."""
        mock_one.return_value = {"id": 42}
        resp = client.get("/api/benchmarks/runs/42/results", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_run_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/runs/999/results", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/runs/1/results")
        assert resp.status_code == 401
